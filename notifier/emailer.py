import os, smtplib
from email.mime.text import MIMEText

def send_rate_brief(to_email: str, subject: str, html_body: str):
    sendgrid_key = os.getenv("SENDGRID_API_KEY")
    if sendgrid_key:
        import requests, json
        r = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {sendgrid_key}", "Content-Type":"application/json"},
            json={
                "personalizations":[{"to":[{"email": to_email}]}],
                "from":{"email":"no-reply@rate-optimizer.local"},
                "subject": subject,
                "content":[{"type":"text/html","value": html_body}],
            },
            timeout=20
        )
        r.raise_for_status()
        return
    # SMTP fallback
    host = os.getenv("SMTP_HOST"); port=int(os.getenv("SMTP_PORT","587"))
    user=os.getenv("SMTP_USER"); pw=os.getenv("SMTP_PASS")
    if not host or not user or not pw:
        print("No email provider configured")
        return
    msg = MIMEText(html_body, "html")
    msg["Subject"]=subject; msg["From"]=user; msg["To"]=to_email
    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, pw)
        s.sendmail(user, [to_email], msg.as_string())
