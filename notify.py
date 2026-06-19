"""
Sends notifications via two free channels:
  1. Ntfy.sh    - instant push, no signup, just a topic name
  2. Email      - Gmail SMTP, works even if push notifications fail

Both are controlled by environment variables - never hardcode credentials.
"""

import os
import smtplib
import requests
from email.mime.text import MIMEText


NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # e.g. "parth-gold-alerts-7f3k"
GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")  # NOT your normal Gmail password
NOTIFY_EMAIL_TO = os.environ.get("NOTIFY_EMAIL_TO", "")  # where alerts get sent


def send_ntfy(title: str, message: str, priority: str = "default") -> bool:
    """Sends a push notification via ntfy.sh. Returns True if it likely succeeded."""
    if not NTFY_TOPIC:
        print("[ntfy] Skipped - NTFY_TOPIC not set.")
        return False
    try:
        resp = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": priority},
            timeout=10,
        )
        ok = resp.status_code == 200
        print(f"[ntfy] {'sent' if ok else 'failed: ' + resp.text}")
        return ok
    except Exception as e:
        print(f"[ntfy] Error: {e}")
        return False


def send_email(subject: str, body: str) -> bool:
    """Sends an email via Gmail SMTP using an App Password (not your real password)."""
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD and NOTIFY_EMAIL_TO):
        print("[email] Skipped - email env vars not fully set.")
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = NOTIFY_EMAIL_TO

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, [NOTIFY_EMAIL_TO], msg.as_string())
        print("[email] sent")
        return True
    except Exception as e:
        print(f"[email] Error: {e}")
        return False


def notify_all(title: str, message: str, priority: str = "default") -> None:
    """Fires both channels. If one fails, the other still goes out."""
    send_ntfy(title, message, priority)
    send_email(title, message)


if __name__ == "__main__":
    # Manual test: python notify.py
    notify_all("Test Alert", "If you see this on your phone and/or inbox, both channels work.")
