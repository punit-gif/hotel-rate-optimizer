# backend/notifier/emailer.py
import os
import requests
import smtplib
from email.message import EmailMessage

SENDGRID_API = "https://api.sendgrid.com/v3/mail/send"

def send_rate_brief(to_email: str, subject: str, html_body: str) -> None:
    """
    Tries SendGrid first (using SENDGRID_API_KEY + FROM_EMAIL [+ FROM_NAME]),
    then falls back to SMTP if SENDGRID is not configured.
    """

    # --- SendGrid path (recommended) ---
    sg_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("FROM_EMAIL")  # must be a verified sender in SendGrid
    from_name = os.getenv("FROM_NAME", "Hotel Rate Optimizer")
    reply_to = os.getenv("REPLY_TO_EMAIL")  # optional

    if sg_key and from_email:
        payload = {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email, "name": from_name},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}],
        }
        if reply_to:
            payload["reply_to"] = {"email": reply_to}

        r = requests.post(
            SENDGRID_API,
            headers={
                "Authorization": f"Bearer {sg_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        # SendGrid returns 202 on success (accepted)
        if r.status_code not in (200, 202):
            raise RuntimeError(f"SendGrid error {r.status_code}: {r.text}")
        return

    # --- SMTP fallback (only if you later set these) ---
    host = os.getenv("SMTP_HOST")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    if host and user and password:
        port = int(os.getenv("SMTP_PORT", "587"))
        sender = os.getenv("SMTP_FROM") or user

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        msg.set_content("HTML email")
        msg.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(host, port) as s:
            s.starttls()
            s.login(user, password)
            s.send_message(msg)
        return

    # Neither SendGrid nor SMTP configured:
    raise RuntimeError("No email transport configured (need SENDGRID_API_KEY+FROM_EMAIL or SMTP_* vars)")
