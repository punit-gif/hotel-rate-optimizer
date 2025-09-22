# ml/model.py
import os
import sys
import warnings
warnings.filterwarnings('ignore')

# --- import path shim so Railway subprocess can import project packages ---
ROOT = os.path.dirname(os.path.dirname(__file__))  # project root
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
from datetime import date, timedelta
from dotenv import load_dotenv
from sqlalchemy import text

from ml.features import build_features                 # keep your relative import semantics
from backend.pricing import compute_baseline, choose_price
from backend.db import get_engine                      # <-- lazy, normalized engine (psycopg v3)

load_dotenv()


def read_tables(engine_):
    """Load reservations and competitor rates from DB; normalize column names."""
    # reservations schema: date, room_type, rooms_sold, rooms_available, adr, revenue
    res = pd.read_sql(
        """
        SELECT date, room_type, rooms_sold, rooms_available, adr
        FROM reservations
        ORDER BY date, room_type
        """,
        engine_
    )
    if not res.empty:
        # derive occupancy % as rooms_sold / rooms_available
        res["occupancy"] = (res["rooms_sold"] / res["rooms_available"] * 100.0).clip(lower=0, upper=100)
        res.rename(columns={"date": "stay_date"}, inplace=True)

    # competitor_rates schema: date, competitor, room_type, rate
    try:
        comp = pd.read_sql(
            """
            SELECT date, competitor, room_type, rate
            FROM competitor_rates
            """,
            engine_
        )
        if not comp.empty:
            comp.rename(columns={"date": "stay_date"}, inplace=True)
    except Exception:
        comp = pd.DataFrame(columns=["stay_date", "competitor", "room_type", "rate"])

    return res, comp


def forecast_demand(train_df: pd.DataFrame, feat_cols: list[str]) -> pd.Series:
    """
    Try LightGBM; fallback to a simple rolling average per room_type.
    Expects train_df['target'] to be occupancy ratio in 0..1 (set by build_features).
    """
    try:
        import lightgbm as lgb
        X = train_df[feat_cols].fillna(method="ffill").fillna(0.0)
        y = train_df["target"]
        model = lgb.LGBMRegressor(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=5,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=42,
        )
        model.fit(X, y)
        pred = pd.Series(model.predict(X), index=train_df.index).clip(0, 1)
        return pred
    except Exception:
        # Fallback: 7-day rolling mean per room_type on 'target'
        return (
            train_df.groupby("room_type")["target"]
            .transform(lambda s: s.rolling(7, min_periods=2).mean().bfill())
            .clip(0, 1)
        )


def main():
    eng = get_engine()

    # Load
    res, comp = read_tables(eng)
    if res.empty:
        print("[ml] No reservation history found.")
        return

    # Build features (expects columns stay_date, room_type, occupancy, adr, etc.)
    feat_df, feat_cols = build_features(res, None if comp.empty else comp)

    # Train/fit & in-sample predictions used as seed for horizon
    feat_df["pred"] = forecast_demand(feat_df, feat_cols)

    # Baseline ADR per room_type (e.g., recent median or function from backend.pricing)
    baselines = compute_baseline(res)  # should return aligned by room_type
    # If compute_baseline returns a Series indexed by room_type, align:
    if baselines.index.name != "room_type":
        baselines.index.name = "room_type"
    feat_df = feat_df.merge(
        baselines.rename("baseline").reset_index(),
        on="room_type",
        how="left",
    )

    # Forecast horizon: 14 days starting day after the last history date
    last_hist = pd.to_datetime(res["stay_date"]).max()
    start = (last_hist + pd.Timedelta(days=1)).normalize()
    horizon = pd.date_range(start, start + pd.Timedelta(days=13), freq="D")  # 14 days inclusive

    # Prepare future rows from most recent per room_type feature state
    future_rows = []
    room_types = sorted(res["room_type"].unique())

    # Pre-compute per-day competitor median if available
    comp_key = None
    comp_by_day_rt = {}
    if not comp.empty:
        comp_key = comp.assign(stay_date=pd.to_datetime(comp["stay_date"]).dt.date)
        comp_by_day_rt = (
            comp_key.groupby(["stay_date", "room_type"])["rate"].median().to_dict()
        )

    # For each future day, for each room_type, take latest known feature snapshot <= that day (or sensible defaults)
    feat_df["stay_date"] = pd.to_datetime(feat_df["stay_date"])
    for d in horizon:
        d_date = d.date()
        is_weekend = int(d.weekday() in (4, 5))  # Fri/Sat treated as weekend
        for rt in room_types:
            hist = feat_df[feat_df["room_type"] == rt]
            last = hist[hist["stay_date"] <= d].tail(1)

            if last.empty:
                # Sensible defaults if no history
                last_occ = float(hist["occupancy"].mean()) if not hist.empty else 50.0
                roll_occ = float(hist["roll_occ_7"].mean()) if "roll_occ_7" in hist.columns and not hist.empty else 50.0
                pred = 0.4 * (last_occ / 100.0) + 0.6 * (roll_occ / 100.0)
                baseline = float(res.loc[res["room_type"] == rt, "adr"].median()) if not res.empty else 100.0
            else:
                row = last.iloc[0]
                baseline = float(row.get("baseline", float(res.loc[res["room_type"] == rt, "adr"].median())))
                pred = float(row["pred"])

            # competitor median for that day+room_type if available
            comp_median = comp_by_day_rt.get((d_date, rt)) if comp_by_day_rt else None

            # Choose recommended ADR
            rec = choose_price(
                baseline=float(baseline),
                proj_occ=float(pred),          # 0..1
                comp_median=None if pd.isna(comp_median) else float(comp_median),
            )

            future_rows.append(
                {
                    "stay_date": d_date,
                    "room_type": rt,
                    "demand_forecast": round(float(pred), 4),
                    "competitor_rate": None if comp_median is None else float(comp_median),
                    "recommended_adr": float(rec),
                }
            )

    fut = pd.DataFrame(future_rows)

    # Persist to forecasts (idempotent upsert per stay_date+room_type)
    with eng.begin() as conn:
        for _, r in fut.iterrows():
            conn.execute(
                text(
                    """
                    INSERT INTO forecasts(stay_date, room_type, demand_forecast, competitor_rate, recommended_adr)
                    VALUES(:stay_date, :room_type, :demand_forecast, :competitor_rate, :recommended_adr)
                    ON CONFLICT (stay_date, room_type) DO UPDATE
                    SET demand_forecast = EXCLUDED.demand_forecast,
                        competitor_rate = EXCLUDED.competitor_rate,
                        recommended_adr = EXCLUDED.recommended_adr
                    """
                ),
                {
                    "stay_date": r["stay_date"],
                    "room_type": r["room_type"],
                    "demand_forecast": float(r["demand_forecast"]),
                    "competitor_rate": None if pd.isna(r["competitor_rate"]) else float(r["competitor_rate"]),
                    "recommended_adr": float(r["recommended_adr"]),
                },
            )

    print(f"[ml] Wrote {len(future_rows)} forecast rows ({len(horizon)} days x {len(room_types)} room types).")


if __name__ == "__main__":
    main()
