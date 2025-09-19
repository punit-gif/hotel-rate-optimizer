# backend/main.py
import os
import json
import logging
from datetime import date, timedelta
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx  # kept in case you use it elsewhere
import jwt

from .db import get_conn
from .auth import create_token, verify_credentials, JWT_SECRET, get_current_user
from .schemas import LoginRequest, ForecastItem, BriefRequest, ETLRunResponse
from .pricing import choose_price  # if used elsewhere; safe to keep

from dotenv import load_dotenv
load_dotenv()

# -------------------------------------------------------------------
# Logging
# -------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("hotel-rate-api")

# -------------------------------------------------------------------
# Settings
# -------------------------------------------------------------------
DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = FastAPI(title="Hotel Rate Optimizer API")

# -------------------------------------------------------------------
# CORS
# -------------------------------------------------------------------
origins = [DASHBOARD_ORIGIN] if DASHBOARD_ORIGIN else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info(f"CORS allow_origins={origins}")

# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True, "service": "hotel-rate-api"}

# -------------------------------------------------------------------
# Auth
# -------------------------------------------------------------------
@app.post("/auth/login")
def login(body: LoginRequest):
    masked = body.email[:2] + "***@" + body.email.split("@")[-1] if "@" in body.email else "***"
    logger.info(f"Login attempt for {masked}")
    user = verify_credentials(body.email, body.password)
    if not user:
        logger.warning(f"Invalid credentials for {masked}")
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user["id"], user["email"])
    logger.info(f"Login success for {masked}, uid={user['id']}")
    return {"token": token}

# -------------------------------------------------------------------
# Forecast
# -------------------------------------------------------------------
@app.get("/forecast", response_model=List[ForecastItem])
def get_forecast(
    start: str = Query(...),
    end: str = Query(...),
    current_user: dict = Depends(get_current_user),
):
    logger.info(f"/forecast requested by uid={current_user['id']} range {start}..{end}")
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)

    with get_conn() as conn:
        # pull forecasts
        rows = conn.execute(
            """
            SELECT stay_date, room_type, demand_forecast, rec_adr
            FROM forecasts
            WHERE stay_date BETWEEN %s AND %s
            ORDER BY stay_date, room_type
            """,
            (start_d, end_d),
        ).fetchall()

        if not rows:
            logger.warning("No forecasts found; advise to run ETL/ML")
            raise HTTPException(status_code=404, detail="No forecasts found. Run ETL/ML.")

        df = pd.DataFrame(rows)

        # competitor median by date+room
        comp = conn.execute(
            """
            SELECT stay_date, room_type,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rate) AS comp_median
            FROM competitor_rates
            WHERE stay_date BETWEEN %s AND %s
            GROUP BY stay_date, room_type
            """,
            (start_d, end_d),
        ).fetchall()

        comp_df = pd.DataFrame(comp) if comp else pd.DataFrame(columns=["stay_date", "room_type", "comp_median"])

    out = []
    for _, r in df.iterrows():
        cm = None
        if not comp_df.empty:
            m = comp_df[(comp_df["stay_date"] == r["stay_date"]) & (comp_df["room_type"] == r["room_type"])]
            if not m.empty:
                cm = float(m.iloc[0]["comp_median"])
        out.append(
            ForecastItem(
                stay_date=str(r["stay_date"]),
                room_type=r["room_type"],
                demand_forecast=float(r["demand_forecast"]),
                competitor_rate=cm,
                recommended_adr=float(r["rec_adr"]),
            )
        )

    logger.info(f"/forecast returning {len(out)} items")
    return out

# -------------------------------------------------------------------
# Brief
# -------------------------------------------------------------------
def _openai_brief(forecast_rows: list[dict]) -> str:
    if not OPENAI_API_KEY:
        logger.info("OPENAI_API_KEY not set; returning fallback brief")
        lines = ["Daily Rate Brief (fallback):"]
        for r in forecast_rows:
            lines.append(
                f"{r['stay_date']} {r['room_type']}: demand {r['demand_forecast']:.0f}, rec ADR ${r['rec_adr']:.2f}"
            )
        return "\n".join(lines)

    logger.info("Generating brief via OpenAI")
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    content = json.dumps(forecast_rows, default=str)
    prompt = (
        "You are a hotel revenue manager. Given JSON of next 7 days with keys: "
        "stay_date, room_type, demand_forecast, rec_adr, comp_median (optional). "
        "Write a concise daily brief (<= 250 words) explaining *why* prices were set based on occupancy outlook, "
        "day of week, and competitor medians. End with 3 bullet action items.\n"
        f"Data: {content}"
    )
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a concise hotel revenue manager."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        timeout=20,  # seconds
    )
    return resp.choices[0].message.content

@app.post("/brief")
def brief(
    req: BriefRequest,
    current_user: dict = Depends(get_current_user),
):
    logger.info(f"/brief requested by uid={current_user['id']} (send={req.send})")
    today = date.today()
    until = today + timedelta(days=6)

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT f.stay_date, f.room_type, f.demand_forecast, f.rec_adr,
                   (
                     SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rate)
                     FROM competitor_rates c
                     WHERE c.stay_date=f.stay_date AND c.room_type=f.room_type
                   ) AS comp_median
            FROM forecasts f
            WHERE f.stay_date BETWEEN %s AND %s
            ORDER BY f.stay_date, f.room_type
            """,
            (today, until),
        ).fetchall()

    if not rows:
        logger.warning("No forecast rows for brief")
        raise HTTPException(status_code=404, detail="No forecast rows")

    data = [dict(r) for r in rows]
    text = _openai_brief(data)

    if req.send:
        to = req.to_email or os.getenv("ADMIN_EMAIL", "admin@example.com")
        logger.info(f"Sending brief email to {to}")
        try:
            from notifier.emailer import send_rate_brief  # type: ignore
        except Exception:
            logger.warning("notifier.emailer not available; skipping email send")
            send_rate_brief = lambda to_email, subject, html_body: None
        send_rate_brief(to, "Daily Rate Brief", f"<pre>{text}</pre>")

    logger.info("Brief generated")
    return {"brief": text}

# -------------------------------------------------------------------
# ETL + ML
# -------------------------------------------------------------------
@app.post("/etl/run", response_model=ETLRunResponse)
def etl_run(current_user: dict = Depends(get_current_user)):
    logger.info(f"/etl/run triggered by uid={current_user['id']}")
    import subprocess, sys

    env = os.environ.copy()

    def run_py(path: str) -> str:
        root = os.path.dirname(os.path.dirname(__file__))  # project root
        cp = subprocess.run(
            [sys.executable, path],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            logger.error(f"Script {path} failed: {cp.stderr.strip()}")
            raise HTTPException(status_code=500, detail=f"Failed {path}: {cp.stderr}")
        logger.info(f"Script {path} OK ({len(cp.stdout)} bytes stdout)")
        return cp.stdout

    etl_out = run_py("etl/etl.py")
    ml_out = run_py("ml/model.py")
    logger.info("/etl/run finished")
    return ETLRunResponse(message="ETL+ML completed")
