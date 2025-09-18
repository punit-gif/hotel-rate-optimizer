import os, sys
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime

load_dotenv()
POSTGRES_URL = os.getenv("POSTGRES_URL")
BASE = Path(__file__).resolve().parents[1]

def upsert_reservations(engine, df):
    with engine.begin() as conn:
        for _, r in df.iterrows():
            conn.execute(text("""
                DELETE FROM reservations WHERE stay_date=:d AND room_type=:rt;
                INSERT INTO reservations(stay_date, room_type, occupancy, adr)
                VALUES(:d,:rt,:occ,:adr);
            """), {"d": r['stay_date'], "rt": r['room_type'], "occ": int(r['occupancy']), "adr": float(r['adr'])})

def upsert_competitors(engine, df):
    with engine.begin() as conn:
        for _, r in df.iterrows():
            conn.execute(text("""
                DELETE FROM competitor_rates WHERE stay_date=:d AND room_type=:rt AND competitor=:c;
                INSERT INTO competitor_rates(stay_date, competitor, room_type, rate)
                VALUES(:d,:c,:rt,:rate);
            """), {"d": r['stay_date'], "rt": r['room_type'], "c": r['competitor'], "rate": float(r['rate'])})

def load_csvs():
    res_path = BASE / "sample_data" / "reservations_30d.csv"
    comp_path = BASE / "sample_data" / "competitors_30d.csv"
    inbox_path = BASE / "inbox" / "nightly.csv"
    res = pd.read_csv(res_path, parse_dates=['date'])
    res = res.rename(columns={'date':'stay_date'})
    res['stay_date'] = res['stay_date'].dt.date
    # optional nightly
    if inbox_path.exists():
        n = pd.read_csv(inbox_path, parse_dates=['date']).rename(columns={'date':'stay_date'})
        n['stay_date'] = n['stay_date'].dt.date
        res = pd.concat([res, n], ignore_index=True).drop_duplicates(['stay_date','room_type'], keep='last')
    comp = pd.read_csv(comp_path, parse_dates=['date']).rename(columns={'date':'stay_date'})
    comp['stay_date'] = comp['stay_date'].dt.date
    return res, comp

def main():
    if not POSTGRES_URL:
        raise RuntimeError("POSTGRES_URL not set")
    engine = create_engine(POSTGRES_URL)
    res, comp = load_csvs()
    upsert_reservations(engine, res)
    upsert_competitors(engine, comp)
    print(f"Upserted {len(res)} reservations and {len(comp)} comp rates")

if __name__ == "__main__":
    main()
