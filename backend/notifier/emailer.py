# backend/notifier/emailer.py
import os
import smtplib
from email.message import EmailMessage

def _require(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(f"Missing environment variable: {name}")
    return val

def send_rate_brief(to_email: str, subject: str, html_body: str) -> None:
    host = _require("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = _require("SMTP_USER")
    password = _require("SMTP_PASS")
    sender = os.getenv("SMTP_FROM") or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content("Your email client does not support HTML.")
    msg.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)
