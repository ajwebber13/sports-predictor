"""
morning_reminder.py — Culture & Pulse Analytics
================================================
Sends a daily morning checklist to Telegram at 9 AM CT.
"""

import os
import requests
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"
CENTRAL_OFFSET   = -5


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET))


def send_message(text: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  TELEGRAM_CHANNEL,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("Reminder sent.")
    else:
        print(f"Telegram error: {r.status_code} {r.text}")


def run():
    today    = get_today_ct()
    date_str = today.strftime("%A, %B %d")
    is_sunday = today.weekday() == 6

    lines = [
        f"☀️ <b>Good Morning — {date_str}</b>",
        "",
        "📋 <b>Daily Checklist</b>",
        "",
        "1️⃣ Open DraftKings/FanDuel — grab today's WNBA prop lines",
        "2️⃣ Double-click <b>load_props.bat</b> — update props_today.txt, save, run",
        "3️⃣ Check Telegram for this morning's slate digest",
        "4️⃣ Check daily recap — yesterday's results already scored",
    ]

    if is_sunday:
        lines.append("")
        lines.append("📊 <b>Sunday:</b> Weekly recap sent — review season record")

    lines.append("")
    lines.append("Let's get it. 🏀")
    lines.append("")
    lines.append("<i>Culture &amp; Pulse Analytics</i>")

    send_message("\n".join(lines))


if __name__ == "__main__":
    run()
