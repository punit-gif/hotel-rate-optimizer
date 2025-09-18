import os, time, bcrypt, jwt
from typing import Optional
from .db import get_conn

JWT_SECRET = os.getenv("JWT_SECRET","please-change-me")
JWT_EXP_SECONDS = 24*3600

def create_token(user_id:int, email:str) -> str:
    payload = {"sub": str(user_id), "email": email, "exp": int(time.time()) + JWT_EXP_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_credentials(email:str, password:str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT id, email, password_hash FROM users WHERE email=%s", (email,)).fetchone()
        if not row: return None
        if bcrypt.checkpw(password.encode(), row["password_hash"].encode() if isinstance(row["password_hash"], str) else row["password_hash"]):
            return {"id": row["id"], "email": row["email"]}
    return None
