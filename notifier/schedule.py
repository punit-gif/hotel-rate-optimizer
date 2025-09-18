import os, requests
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
import pytz

API_BASE = os.getenv("API_BASE","http://localhost:8080")
JWT = os.getenv("CRON_JWT")  # pre-generated token for the admin
TZ = pytz.timezone(os.getenv("SCHEDULE_TZ","America/Chicago"))

def send_brief():
    headers = {"Authorization": f"Bearer {JWT}"}
    r = requests.post(f"{API_BASE}/brief", json={"send": True}, headers=headers, timeout=30)
    print("Brief sent", r.status_code, r.text[:120])

if __name__ == "__main__":
    sched = BlockingScheduler(timezone=TZ)
    # Every day at 7:00 local time
    sched.add_job(send_brief, "cron", hour=7, minute=0)
    print("Scheduler started...")
    sched.start()
