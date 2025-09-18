# backend/auth.py
import os
import time
from typing import Optional, Dict, Any

import bcrypt
import jwt
from fastapi import Request, HTTPException

from .db import get_conn

# JWT settings
JWT_SECRET = os.getenv("JWT_SECRET", "please-change-me")
JWT_ALG = "HS256"
JWT_EXP_SECONDS = 24 * 3600


def create_token(user_id: int, email: str) -> str:
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": int(time.time()) + JWT_EXP_SECONDS,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def verify_credentials(email: str, password: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email=%s",
            (email,),
        ).fetchone()
        if not row:
            return None

        stored_hash = row["password_hash"]
        if isinstance(stored_hash, str):
            stored_hash = stored_hash.encode()

        if bcrypt.checkpw(password.encode(), stored_hash):
            return {"id": row["id"], "email": row["email"]}

    return None


def _extract_bearer_token(request: Request) -> Optional[str]:
    """
    Try several places for the JWT:
    1) Authorization: Bearer <token>
    2) X-Forwarded-Authorization: Bearer <token>  (some proxies forward here)
    3) token=<jwt> query param (fallback if proxies/shell drop headers)
    """
    for name in (
        "authorization",
        "Authorization",
        "x-forwarded-authorization",
        "X-Forwarded-Authorization",
    ):
        val = request.headers.get(name)
        if val:
            parts = val.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1].strip()

    qp = request.query_params.get("token")
    if qp:
        return qp.strip()

    return None


def get_current_user(request: Request) -> Dict[str, Any]:
    token = _extract_bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        user_id = data.get("sub")
        email = data.get("email")

        # basic sanity checks
        if user_id is None or email is None:
            raise HTTPException(status_code=401, detail="Invalid token")

        return {"id": int(user_id), "email": email}

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
