# backend/auth.py
import os
import time
from typing import Optional, Dict, Any

import bcrypt
import jwt
from fastapi import Request, HTTPException, Header, Query, Cookie

from .db import get_conn

# JWT settings
JWT_SECRET = os.getenv("JWT_SECRET", "please-change-me")
JWT_ALG = "HS256"
JWT_EXP_SECONDS = int(os.getenv("JWT_EXP_SECONDS", 24 * 3600))


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


def _from_auth_header(value: Optional[str]) -> Optional[str]:
    """
    Accept either 'Bearer <jwt>' or a raw JWT (some proxies strip the prefix).
    """
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if value.lower().startswith("bearer "):
        return value.split(" ", 1)[1].strip()
    return value


def get_current_user(
    request: Request,
    # headers (FastAPI will inject these if present)
    authorization: Optional[str] = Header(None, convert_underscores=False),
    x_forwarded_authorization: Optional[str] = Header(
        None, alias="X-Forwarded-Authorization", convert_underscores=False
    ),
    # query-string fallbacks
    token_q: Optional[str] = Query(None, alias="token"),
    access_token_q: Optional[str] = Query(None, alias="access_token"),
    # cookie fallbacks (if you ever need them)
    authorization_cookie: Optional[str] = Cookie(None, alias="Authorization"),
    access_token_cookie: Optional[str] = Cookie(None, alias="access_token"),
) -> Dict[str, Any]:
    """
    Extract JWT from multiple locations in a robust order of precedence.
    """
    candidates = [
        _from_auth_header(authorization),
        _from_auth_header(x_forwarded_authorization),
        token_q,
        access_token_q,
        authorization_cookie,
        access_token_cookie,
    ]
    token = next((t for t in candidates if t), None)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        uid = data.get("sub")
        email = data.get("email")
        if not uid or not email:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"id": int(uid), "email": email}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
