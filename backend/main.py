# backend/main.py
import os
import json
import logging
from datetime import date, timedelta
from typing import List, Optional, Dict, Any

import pandas as pd
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
import jwt  # PyJWT

from .db import get_conn
from .auth import create_token, verify_credentials, JWT_SECRET
from .schemas import LoginRequest, ForecastItem, BriefRequest, ETLRunResponse

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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# CORS origins
_default_origins = [
    os.getenv("DASHBOARD_ORIGIN"),
    "https://dashboard-frontend-production-3d65.up.railway.app",
    "http://localhost:8501",
    "http://localhost:5173",
    "http://localhost:3000",
]
origins = [o for o in _default_origins if o] or ["*"]

app = FastAPI(title="Hotel Rate Optimizer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)
logger.info(f"CORS allow_origins={origins}")

# -------------------------------------------------------------------
# Auth helpers (header or ?token=)
# -------------------------------------------------------------------
def _token_from_request(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    q = request.query_params.get("token")
    if q:
        return q.strip()
    return None

def _load_user_by_id(uid: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, role FROM users WHERE id = %s",
            (uid,),
        ).fetchone()
        return dict(row) if row else None

def _decode_jwt(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception as e:
        logger.warning(f"JWT decode failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid or expired token")

async def current_user(request: Request) -> Dict[str, Any]:
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    claims = _decode_jwt(token)
    uid = claims.get("sub") or claims.get("user_id") or claims.get("id")
    email = claims.get("email")
    try:
        uid_int = int(uid)
    except Exception:
        logger.warning(f"JWT missing/invalid user id: {uid}")
        raise HTTPException(status_code=401, detail="Invalid token payload")
    user = _load_user_by_id(uid_int)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    user.setdefault("email", email)
    return user

# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True, "service": "hotel-rate-api"}

@app.get("/healthz/db")
def healthz_db():
    with get_conn() as conn:
        fc = conn.execute("SELECT COUNT(*) AS c FROM forecasts").fetchone()["c"]
        cr = conn.execute("SELECT COUNT(*) AS c FROM competitor_rates").fetchone()["c"]
    return {"forecasts": fc, "competitor_rates": cr}

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
    return {"token": token, "user": {"id": user["id"], "email": user["email"], "role": user.get("role", "gm")}}

# -------------------------------------------------------------------
# Forecast
# -------------------------------------------------------------------
@app.get("/forecast", response_model=List[ForecastItem])
def get_forecast(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    user: dict = Depends(current_user),
):
    logger.info(f"/forecast by uid={user['id']} range {start}..{end}")
    start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)

    with get_conn() as conn:
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

    out: List[ForecastItem] = []
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
def _openai_brief(forecast_rows: List[Dict[str, Any]]) -> str:
    if not OPENAI_API_KEY:
        logger.info("OPENAI_API_KEY not set; returning fallback brief")
        lines = ["Daily Rate Brief (fallback):"]
        for r in forecast_rows:
            rec = r.get("rec_adr") or r.get("recommended_adr")
            lines.append(
                f"{r['stay_date']} {r['room_type']}: demand {float(r['demand_forecast']):.0f}, rec ADR ${float(rec):.2f}"
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
        timeout=20,
    )
    return resp.choices[0].message.content

@app.post("/brief")
def brief(
    req: BriefRequest,
    user: dict = Depends(current_user),
):
    logger.info(f"/brief by uid={user['id']} (send={req.send})")
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

    email_status = "skipped"
    email_error: Optional[str] = None

    if req.send:
        to = (req.to_email or os.getenv("ADMIN_EMAIL", "admin@example.com")).strip()
        logger.info(f"Attempting to email brief to {to}")
        try:
            from notifier.emailer import send_rate_brief  # uses SMTP; see notifier/emailer.py
            send_rate_brief(to, "Daily Rate Brief", f"<pre>{text}</pre>")
            email_status = "sent"
            logger.info("Email sent.")
        except Exception as e:
            # NEVER fail the endpoint due to email issues
            email_status = "error"
            email_error = str(e)
            logger.exception("Email send failed")

    return {"brief": text, "email_status": email_status, "email_error": email_error}

# -------------------------------------------------------------------
# ETL + ML
# -------------------------------------------------------------------
@app.post("/etl/run", response_model=ETLRunResponse)
def etl_run(user: dict = Depends(current_user)):
    logger.info(f"/etl/run triggered by uid={user['id']}")
    import subprocess, sys, pathlib

    env = os.environ.copy()
    root = pathlib.Path(__file__).resolve().parents[1]

    def run_py(path: str) -> str:
        cp = subprocess.run(
            [sys.executable, path],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            logger.error(f"Script {path} failed: {cp.stderr.strip()}")
            raise HTTPException(status_code=500, detail=f"Failed {path}: {cp.stderr}")
        logger.info(f"Script {path} OK ({len(cp.stdout)} bytes stdout)")
        return cp.stdout

    run_py("etl/etl.py")
    run_py("ml/model.py")
    logger.info("/etl/run finished")
    return ETLRunResponse(message="ETL+ML completed")
