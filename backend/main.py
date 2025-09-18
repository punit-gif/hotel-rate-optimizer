import os, json, logging, math
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

import pandas as pd
import httpx
from fastapi import FastAPI, Depends, HTTPException, Query, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import jwt

from .db import get_conn
from .auth import create_token, verify_credentials, JWT_SECRET
from .schemas import LoginRequest, ForecastItem, BriefRequest, ETLRunResponse
from .pricing import choose_price

from dotenv import load_dotenv
load_dotenv()

DASHBOARD_ORIGIN = os.getenv("DASHBOARD_ORIGIN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = FastAPI(title="Hotel Rate Optimizer API")

# CORS
origins = [DASHBOARD_ORIGIN] if DASHBOARD_ORIGIN else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def require_jwt(auth: Optional[str] = Header(None)):
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = auth.split(" ",1)[1]
    try:
        jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return True
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/auth/login")
def login(body: LoginRequest):
    user = verify_credentials(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user["id"], user["email"])
    return {"token": token}

@app.get("/forecast", response_model=List[ForecastItem])
def get_forecast(start: str = Query(...), end: str = Query(...), authorized: bool = Depends(require_jwt)):
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    with get_conn() as conn:
        # pull forecasts
        rows = conn.execute(
            "SELECT stay_date, room_type, demand_forecast, rec_adr FROM forecasts WHERE stay_date BETWEEN %s AND %s ORDER BY stay_date, room_type",
            (start_d, end_d)
        ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="No forecasts found. Run ETL/ML.")
        df = pd.DataFrame(rows)
        # competitor median by date+room
        comp = conn.execute(
            """SELECT stay_date, room_type, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rate) AS comp_median
                 FROM competitor_rates
                 WHERE stay_date BETWEEN %s AND %s
                 GROUP BY stay_date, room_type""",
            (start_d, end_d)
        ).fetchall()
        comp_df = pd.DataFrame(comp) if comp else pd.DataFrame(columns=['stay_date','room_type','comp_median'])
        out = []
        for _, r in df.iterrows():
            cm = None
            if not comp_df.empty:
                m = comp_df[(comp_df['stay_date']==r['stay_date']) & (comp_df['room_type']==r['room_type'])]
                if not m.empty: cm = float(m.iloc[0]['comp_median'])
            out.append(ForecastItem(
                stay_date=str(r['stay_date']),
                room_type=r['room_type'],
                demand_forecast=float(r['demand_forecast']),
                competitor_rate=cm,
                recommended_adr=float(r['rec_adr'])
            ))
        return out

def _openai_brief(forecast_rows: list[dict]) -> str:
    if not OPENAI_API_KEY:
        # Fallback brief
        lines = ["Daily Rate Brief (fallback):"]
        for r in forecast_rows:
            lines.append(f"{r['stay_date']} {r['room_type']}: demand {r['demand_forecast']:.0f}, rec ADR ${r['rec_adr']:.2f}")
        return "\n".join(lines)

    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY)
    content = json.dumps(forecast_rows, default=str)
    prompt = f"""You are a hotel revenue manager. Given JSON of next 7 days with keys:
    stay_date, room_type, demand_forecast, rec_adr, comp_median (optional).
    Write a concise daily brief (<= 250 words) explaining *why* prices were set based on occupancy outlook,
    day of week, and competitor medians. End with 3 bullet action items.
    Data: {content} """
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"system","content":"You are a concise hotel revenue manager."},
                  {"role":"user","content":prompt}],
        temperature=0.3,
        timeout=20_000
    )
    return resp.choices[0].message.content

from . import pricing as pricing_mod

@app.post("/brief")
def brief(req: BriefRequest, authorized: bool = Depends(require_jwt)):
    today = date.today()
    until = today + timedelta(days=6)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT f.stay_date, f.room_type, f.demand_forecast, f.rec_adr,
                       (SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rate)
                        FROM competitor_rates c
                        WHERE c.stay_date=f.stay_date AND c.room_type=f.room_type) AS comp_median
                FROM forecasts f
                WHERE f.stay_date BETWEEN %s AND %s
                ORDER BY f.stay_date, f.room_type""", (today, until)
        ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="No forecast rows")
        data = [dict(r) for r in rows]
    text = _openai_brief(data)
    if req.send:
        to = req.to_email or os.getenv("ADMIN_EMAIL","admin@example.com")
        from . import mailer_stub
        try:
            from notifier.emailer import send_rate_brief  # type: ignore
        except Exception:
            send_rate_brief = lambda to_email, subject, html_body: None
        send_rate_brief(to, "Daily Rate Brief", f"<pre>{text}</pre>")
    return {"brief": text}

@app.post("/etl/run", response_model=ETLRunResponse)
def etl_run(authorized: bool = Depends(require_jwt)):
    # Run ETL then ML
    import subprocess, sys, os
    env = os.environ.copy()
    def run_py(path):
        cp = subprocess.run([sys.executable, path], cwd=os.path.dirname(os.path.dirname(__file__)), env=env, capture_output=True, text=True)
        if cp.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Failed {path}: {cp.stderr}")
        return cp.stdout
    etl_out = run_py("etl/etl.py")
    ml_out = run_py("ml/model.py")
    return ETLRunResponse(message="ETL+ML completed")
