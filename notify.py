"""
Sends push notifications via Ntfy.sh - free, no signup, no blocked ports.

Why not email? Render's free tier blocks outbound SMTP ports (25, 465, 587),
so Gmail SMTP hangs and times out. Ntfy works over normal HTTPS (port 443),
which Render does not block - so we use Ntfy only, kept simple.
"""

import os
import requests


NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # e.g. "parth-gold-alerts-7f3k"


def _ascii_safe(text: str) -> str:
    """
    HTTP headers must be latin-1/ASCII safe. Emojis (like checkmarks, circles)
    break ntfy's Title header. Strip non-ASCII characters for the header only -
    the message body can still contain emojis freely.
    """
    return text.encode("ascii", "ignore").decode("ascii").strip()


def send_ntfy(title: str, message: str, priority: str = "default") -> bool:
    """Sends a push notification via ntfy.sh. Returns True if it likely succeeded."""
    if not NTFY_TOPIC:
        print("[ntfy] Skipped - NTFY_TOPIC not set.")
        return False
    try:
        safe_title = _ascii_safe(title) or "Alert"
        resp = requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=message.encode("utf-8"),
            headers={"Title": safe_title, "Priority": priority},
            timeout=10,
        )
        ok = resp.status_code == 200
        print(f"[ntfy] {'sent' if ok else 'failed: ' + resp.text}")
        return ok
    except Exception as e:
        print(f"[ntfy] Error: {e}")
        return False


def notify_all(title: str, message: str, priority: str = "default") -> None:
    """Single notification channel (Ntfy). Kept as notify_all() so main.py doesn't need changes."""
    send_ntfy(title, message, priority)


if __name__ == "__main__":
    # Manual test: python notify.py
    notify_all("Test Alert", "If you see this on your phone, Ntfy is working.")
