import os
from functools import lru_cache
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def _get_raw_url() -> Optional[str]:
    """
    Pull a Postgres URL from common env var names.
    Accepts POSTGRES_URL, DATABASE_URL, or PGDATABASE_URL.
    """
    return (
        os.getenv("POSTGRES_URL")
        or os.getenv("DATABASE_URL")
        or os.getenv("PGDATABASE_URL")
    )


def _normalize_pg_url_for_sqlalchemy(url: Optional[str]) -> Optional[str]:
    """
    SQLAlchemy + psycopg (v3) expects 'postgresql+psycopg://'.
    Normalize common forms to that dialect.
    """
    if not url:
        return None
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _to_psycopg_dsn(url: Optional[str]) -> Optional[str]:
    """
    psycopg.connect() expects a plain 'postgresql://' (or DSN string),
    not 'postgresql+psycopg://'. Convert if needed.
    """
    if not url:
        return None
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        # psycopg understands 'postgres://' but standardize to 'postgresql://'
        return url.replace("postgres://", "postgresql://", 1)
    return url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """
    Lazy, cached SQLAlchemy engine using the psycopg v3 dialect.
    Called at runtime by API/ETL/ML so import-time env gaps don't break.
    """
    raw = _get_raw_url()
    norm = _normalize_pg_url_for_sqlalchemy(raw)
    if not norm:
        raise RuntimeError("POSTGRES_URL/DATABASE_URL not set")
    return create_engine(norm, pool_pre_ping=True, future=True)


def get_conn():
    """
    Direct psycopg3 connection with dict_row factory.
    Useful for scripts or places where you want a raw connection.
    """
    raw = _get_raw_url()
    dsn = _to_psycopg_dsn(raw)
    if not dsn:
        raise RuntimeError("POSTGRES_URL/DATABASE_URL not set")
    return psycopg.connect(dsn, row_factory=dict_row)
