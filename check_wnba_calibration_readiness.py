"""
check_wnba_calibration_readiness.py

Checks how many graded WNBA predictions have a real (non-NULL) model_prob.
Sends a Discord alert once the count crosses the threshold needed to trust
calibration_audit.py's output (150 graded picks minimum).

ASSUMPTIONS — adjust these to match your real schema/imports if different:
  - db.py (or wherever get_conn() lives) exposes get_conn()
  - predictions table has columns: sport, model_prob, id
  - results table has columns: prediction_id, correct
  - A Discord webhook helper already exists somewhere in your alert scripts
    (e.g. send_discord_alert(message) in discord_alerts.py) — import it below
    instead of the placeholder if you have one.

Run manually anytime:
    python check_wnba_calibration_readiness.py

Or schedule it (e.g. daily via GitHub Actions / cron) so it checks itself
and only pings you once the threshold is hit.
"""

import os
import sys

# --- adjust this import to match your real project structure ---
try:
    from database import get_conn  # your existing Postgres/Supabase connector
except ImportError:
    print("ERROR: could not import get_conn(). Update the import path at the top of this script.")
    sys.exit(1)

THRESHOLD = 150
SPORT = "wnba"

# Path to a small local file used to avoid sending duplicate alerts
STATE_FILE = ".wnba_calibration_alert_sent"


def get_graded_model_prob_count(conn) -> int:
    """
    Counts graded WNBA predictions (joined to results) that have a real
    (non-NULL) model_prob. Adjust table/column names if yours differ.
    """
    query = """
        SELECT COUNT(*)
        FROM predictions p
        JOIN results r ON r.prediction_id = p.id
        WHERE p.sport = ?
          AND p.model_prob IS NOT NULL
    """
    cur = conn.cursor()
    cur.execute(query, (SPORT,))
    count = cur.fetchone()[0]
    cur.close()
    return count


def send_discord_alert(message: str):
    """
    Placeholder — replace this with your real Discord webhook send function
    if one already exists in your alert scripts (recommended), e.g.:

        from discord_alerts import send_discord_message
        send_discord_message(message)
    """
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("No DISCORD_WEBHOOK_URL set — printing alert instead:")
        print(message)
        return

    import requests
    resp = requests.post(webhook_url, json={"content": message})
    resp.raise_for_status()


def already_alerted() -> bool:
    return os.path.exists(STATE_FILE)


def mark_alerted():
    with open(STATE_FILE, "w") as f:
        f.write("sent")


def main():
    conn = get_conn()
    try:
        count = get_graded_model_prob_count(conn)
    finally:
        conn.close()

    print(f"WNBA graded picks with real model_prob: {count} / {THRESHOLD}")

    if count >= THRESHOLD and not already_alerted():
        message = (
            f"📊 WNBA calibration data ready — {count} graded picks with real "
            f"model_prob (threshold: {THRESHOLD}). Run calibration_audit.py "
            f"--sport wnba now."
        )
        send_discord_alert(message)
        mark_alerted()
        print("Alert sent.")
    elif count >= THRESHOLD:
        print("Threshold already met — alert already sent previously.")
    else:
        print(f"Not ready yet — need {THRESHOLD - count} more graded picks.")


if __name__ == "__main__":
    main()
