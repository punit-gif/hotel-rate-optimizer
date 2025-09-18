import os
import psycopg
from psycopg.rows import dict_row

POSTGRES_URL = os.getenv("POSTGRES_URL")

def get_conn():
    if not POSTGRES_URL:
        raise RuntimeError("POSTGRES_URL not set")
    return psycopg.connect(POSTGRES_URL, row_factory=dict_row)
