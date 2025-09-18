import os, warnings
warnings.filterwarnings('ignore')
import pandas as pd
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from .features import build_features
from backend.pricing import compute_baseline, choose_price

load_dotenv()

POSTGRES_URL = os.getenv("POSTGRES_URL")

def read_tables(engine):
    res = pd.read_sql("SELECT stay_date, room_type, occupancy, adr FROM reservations ORDER BY stay_date, room_type", engine)
    try:
        comp = pd.read_sql("SELECT stay_date, competitor, room_type, rate FROM competitor_rates", engine)
    except Exception:
        comp = pd.DataFrame(columns=['stay_date','competitor','room_type','rate'])
    return res, comp

def forecast_demand(train_df, feat_cols):
    # Try LightGBM; fallback to Prophet by naive heuristic (per room_type)
    try:
        import lightgbm as lgb
        X = train_df[feat_cols].fillna(method='ffill').fillna(0.0)
        y = train_df['target']
        model = lgb.LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=5, subsample=0.9, colsample_bytree=0.9, random_state=42)
        model.fit(X, y)
        train_df['pred'] = model.predict(X).clip(0,1)
        return train_df['pred']
    except Exception:
        # Prophet fallback: simple moving average per room_type
        return train_df.groupby('room_type')['target'].transform(lambda s: s.rolling(7, min_periods=2).mean().fillna(method='bfill')).clip(0,1)

def main():
    if not POSTGRES_URL:
        raise RuntimeError("POSTGRES_URL not set")
    engine = create_engine(POSTGRES_URL)
    res, comp = read_tables(engine)
    if res.empty:
        print("No reservations data")
        return
    # Build features
    feat_df, feat_cols = build_features(res, comp if not comp.empty else None)
    # Forecast
    feat_df['pred'] = forecast_demand(feat_df, feat_cols)
    # Compute baseline per room_type
    baselines = compute_baseline(res)
    feat_df['baseline'] = baselines.values
    # Choose recommended ADR for the *future* dates (from tomorrow 14-day horizon)
    today = pd.to_datetime(date.today())
    horizon = pd.date_range(today, today + timedelta(days=14), freq='D')
    # Build per (date, room_type) rows by last known features; use comp median from comp table
    future_rows = []
    room_types = sorted(res['room_type'].unique())
    for d in horizon:
        for rt in room_types:
            hist = feat_df[feat_df['room_type']==rt]
            last = hist[hist['stay_date']<=d].tail(1)
            if last.empty:
                # synthesize defaults
                dow = d.dayofweek
                last_occ = hist['occupancy'].mean() if not hist.empty else 50
                roll = hist['roll_occ_7'].mean() if not hist.empty else 50
                is_weekend = int(dow in [4,5])
                comp_median = comp[(comp['stay_date']==d.date()) & (comp['room_type']==rt)]['rate'].median() if not comp.empty else None
                baseline = res[res['room_type']==rt]['adr'].median() if not res.empty else 100.0
                pred = (0.4* (last_occ/100.0) + 0.6* (roll/100.0))
            else:
                row = last.iloc[0]
                dow = d.dayofweek
                is_weekend = int(dow in [4,5])
                comp_median = comp[(comp['stay_date']==d.date()) & (comp['room_type']==rt)]['rate'].median() if not comp.empty else None
                baseline = row.get('baseline', res[res['room_type']==rt]['adr'].median())
                pred = float(row['pred'])
            # price selection
            rec = choose_price(baseline=float(baseline), proj_occ=float(pred), comp_median=None if pd.isna(comp_median) else float(comp_median))
            future_rows.append({
                'run_date': date.today(),
                'stay_date': d.date(),
                'room_type': rt,
                'demand_forecast': round(float(pred),4),
                'rec_adr': rec,
                'notes': f"Baseline={baseline:.2f}; comp={comp_median if comp_median==comp_median else 'NA'}; weekend={bool(is_weekend)}"
            })
    fut = pd.DataFrame(future_rows)
    # Persist to forecasts (upsert per stay_date+room_type)
    with engine.begin() as conn:
        for _, r in fut.iterrows():
            conn.execute(text("""
                DELETE FROM forecasts WHERE stay_date=:stay AND room_type=:room;
            """), {"stay": r['stay_date'], "room": r['room_type']})
            conn.execute(text("""
                INSERT INTO forecasts(run_date, stay_date, room_type, demand_forecast, rec_adr, notes)
                VALUES(:run_date,:stay_date,:room_type,:demand,:rec,:notes);
            """), {
                "run_date": r['run_date'],
                "stay_date": r['stay_date'],
                "room_type": r['room_type'],
                "demand": float(r['demand_forecast']),
                "rec": float(r['rec_adr']),
                "notes": r['notes']
            })
    print(f"wrote {len(future_rows)} forecast rows")

if __name__ == "__main__":
    main()
