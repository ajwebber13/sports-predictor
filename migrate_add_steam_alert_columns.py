"""
migrate_add_steam_alert_columns.py — Culture & Pulse Analytics
=======================================================
One-time fix: render_job.py's steam alert (--retry, noon + 3 PM CT)
had no memory of what it already sent. log_line_movement() always
compares the CURRENT price against the game's untouched opening
price, so a line that crossed the sharp threshold by noon and simply
stayed there re-triggered the exact same Discord "Line Movement
Alert" again at 3 PM.

Adds two nullable columns to line_movement:
  - steam_alerted_at   (TEXT/TIMESTAMP) — when this row was last
    included in a successfully-sent steam alert. NULL = never alerted.
  - steam_alerted_move (INTEGER) — the signed movement value AT that
    last alert, so a later retry can tell "same move, already sent"
    from "moved further / reversed direction, this IS new" instead of
    just checking presence of a timestamp.

See database.py's get_steam_alert_state() / mark_steam_alerted() and
render_job.py's steam-alert block (2026-09-08) for how these are used.

Usage:
    python migrate_add_steam_alert_columns.py            # shows what it'll do, asks to confirm
    python migrate_add_steam_alert_columns.py --yes      # skips the confirmation prompt
"""

import argparse
import sys

sys.path.insert(0, ".")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn


def run(skip_confirm: bool = False):
    conn = get_conn()
    c = conn.cursor()

    print("This will add two nullable columns to line_movement:")
    print("  steam_alerted_at   TEXT")
    print("  steam_alerted_move INTEGER")

    if not skip_confirm:
        answer = input("\nApply this change? Type YES to proceed: ").strip()
        if answer != "YES":
            print("Cancelled — nothing changed.")
            conn.close()
            return

    for col, coltype in (("steam_alerted_at", "TEXT"), ("steam_alerted_move", "INTEGER")):
        try:
            c.execute(f"ALTER TABLE line_movement ADD COLUMN {col} {coltype}")
            conn.commit()
            print(f"  Added {col}.")
        except Exception as e:
            conn.rollback()
            print(f"  Skipped {col} (likely already exists): {e}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    run(skip_confirm=args.yes)
