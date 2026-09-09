"""
migrate_add_alerted_columns.py — Culture & Pulse Analytics
=======================================================
One-time fix: "log full slate" (2026-09-09). Every game/market the
model scores now gets a row in `predictions` regardless of confidence
or edge — the 55%/65% gates and throttle_bets() still control what
reaches Discord, they just stopped also controlling what gets logged.
That means a row in `predictions` no longer implies it was alerted.

Adds two columns to predictions:
  - alerted            (BOOLEAN, DEFAULT true) — whether this row
    actually cleared every gate and was eligible to send. Existing
    rows all predate this feature, so every one of them WAS an
    alerted pick by definition — DEFAULT true backfills them
    correctly, not just as a placeholder.
  - suppressed_reason   (TEXT, nullable) — why a row has alerted=false,
    e.g. "Confidence 41.0% below minimum 55%" or "Edge 3.2% below
    minimum 5%". NULL for alerted rows.

See database.py's log_prediction() and render_job.py's WNBA/MLB and
NFL/CFB alert flows for how these are populated, and
performance_tracker.py / dashboard.py's load_picks() for where
alerted=true is now required so season-record/ROI/calibration numbers
don't silently start counting picks nobody ever saw.

Usage:
    python migrate_add_alerted_columns.py            # shows what it'll do, asks to confirm
    python migrate_add_alerted_columns.py --yes      # skips the confirmation prompt
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

    print("This will add two columns to predictions:")
    print("  alerted            BOOLEAN DEFAULT true")
    print("  suppressed_reason  TEXT")

    if not skip_confirm:
        answer = input("\nApply this change? Type YES to proceed: ").strip()
        if answer != "YES":
            print("Cancelled — nothing changed.")
            conn.close()
            return

    try:
        c.execute("ALTER TABLE predictions ADD COLUMN alerted BOOLEAN DEFAULT true")
        conn.commit()
        print("  Added alerted.")
    except Exception as e:
        conn.rollback()
        print(f"  Skipped alerted (likely already exists): {e}")

    try:
        c.execute("ALTER TABLE predictions ADD COLUMN suppressed_reason TEXT")
        conn.commit()
        print("  Added suppressed_reason.")
    except Exception as e:
        conn.rollback()
        print(f"  Skipped suppressed_reason (likely already exists): {e}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    run(skip_confirm=args.yes)
