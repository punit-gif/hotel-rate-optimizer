# etl/etl.py
import os
import sys
import csv
from pathlib import Path
from sqlalchemy import text

# --- Make project root importable (Railway subprocess safe) ---
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Use LAZY engine factory (prevents import-time failures)
from backend.db import get_engine  # <- lazy, normalized to postgresql+psycopg

BASE = ROOT
RES_PATH = BASE / "sample_data" / "reservations_30d.csv"
COMP_PATH = BASE / "sample_data" / "competitors_30d.csv"
INBOX_PATH = BASE / "inbox" / "nightly.csv"  # header-only placeholder in Sprint 0


def upsert_reservations(conn) -> int:
    """
    Upsert reservations from sample_data/reservations_30d.csv
    Expected columns:
      date,room_type,rooms_sold,rooms_available,adr,revenue
    """
    inserted = 0
    if not RES_PATH.exists():
        print(f"[etl] WARN: {RES_PATH} not found; skipping reservations.")
        return 0

    with RES_PATH.open(newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for row in rd:
            sql = text("""
                INSERT INTO reservations (date, room_type, rooms_sold, rooms_available, adr, revenue)
                VALUES (:date, :room_type, :rooms_sold, :rooms_available, :adr, :revenue)
                ON CONFLICT (date, room_type) DO UPDATE
                SET rooms_sold     = EXCLUDED.rooms_sold,
                    rooms_available = EXCLUDED.rooms_available,
                    adr             = EXCLUDED.adr,
                    revenue         = EXCLUDED.revenue
            """)
            conn.execute(sql, {
                "date": row["date"],
                "room_type": row["room_type"],
                "rooms_sold": int(row["rooms_sold"]),
                "rooms_available": int(row["rooms_available"]),
                "adr": float(row["adr"]),
                "revenue": float(row["revenue"]),
            })
            inserted += 1
    return inserted


def upsert_competitors(conn) -> int:
    """
    Upsert competitor rates from sample_data/competitors_30d.csv
    Expected columns:
      date,competitor,room_type,rate
    """
    inserted = 0
    if not COMP_PATH.exists():
        print(f"[etl] WARN: {COMP_PATH} not found; skipping competitor rates.")
        return 0

    with COMP_PATH.open(newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        for row in rd:
            sql = text("""
                INSERT INTO competitor_rates (date, competitor, room_type, rate)
                VALUES (:date, :competitor, :room_type, :rate)
                ON CONFLICT (date, competitor, room_type) DO UPDATE
                SET rate = EXCLUDED.rate
            """)
            conn.execute(sql, {
                "date": row["date"],
                "competitor": row["competitor"],
                "room_type": row["room_type"],
                "rate": float(row["rate"]),
            })
            inserted += 1
    return inserted


def maybe_ingest_nightly(conn) -> int:
    """
    Optional: tolerate header-only nightly.csv without error.
    Format (placeholder): date,room_type,occupancy,adr
    We **skip** ingest in Sprint 0 because it doesn’t match the baseline schema
    (rooms_sold/rooms_available). Returning 0 keeps logs clean.
    """
    if not INBOX_PATH.exists():
        return 0
    # If the file only has headers or is empty, do nothing.
    try:
        with INBOX_PATH.open("r", encoding="utf-8") as f:
            lines = [ln for ln in f.readlines() if ln.strip()]
        if len(lines) <= 1:
            return 0
    except Exception:
        return 0
    # If you later want to map occupancy → rooms_sold, add logic here.
    return 0


def main():
    eng = get_engine()  # <- create engine only when running
    with eng.begin() as conn:
        print("[etl] Connected.")
        r = upsert_reservations(conn)
        c = upsert_competitors(conn)
        n = maybe_ingest_nightly(conn)
        print(f"[etl] Upserted {r} reservations and {c} competitor rates. (nightly added {n})")


if __name__ == "__main__":
    main()
