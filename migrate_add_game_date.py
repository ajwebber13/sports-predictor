"""
migrate_add_game_date.py — Culture & Pulse Analytics
=======================================================
One-time fix: predictions.date meant "the day this row was logged,"
not "the day the game is played." Those were always assumed identical
until CFB started generating picks days before kickoff (see the
get_game_times("cfb") fix, 2026-09-04) — a Thursday alert for a
Saturday game got stamped date='2026-09-03', so auto_results.py's
grading query (WHERE date = <the day being graded>) would never find
it: a Saturday query looks for date='2026-09-05' and comes up empty.

This adds a real game_date column, backfills it, and points
auto_results.py's grading queries at it instead (done in that file
separately from this script — see its 2026-09-04 fixes).

Backfill strategy:
  1. Default every row's game_date to its existing `date` value. This
     is correct for the overwhelming majority of rows — every sport
     except CFB was already correctly restricted to same-day games at
     log time, so `date` already equals the real game day for them.
  2. Specifically correct the exact rows this session found and
     verified against ESPN: 4 CFB predictions logged 2026-09-03 for
     games that actually kick off 2026-09-05. This is a targeted,
     hand-verified fix for the known-affected rows, not a general
     historical crawl — a broader backfill (re-deriving game_date for
     every historical row across every sport via ESPN lookups) would
     need its own, separately-scoped effort.

Usage:
    python migrate_add_game_date.py            # shows what it'll do, asks to confirm
    python migrate_add_game_date.py --yes      # skips the confirmation prompt
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

# Hand-verified against ESPN this session (2026-09-04): all four kick
# off 2026-09-05, not the 2026-09-03 they were logged on.
KNOWN_MISDATED_CFB_ROWS = {
    # (game, market): correct game_date
    ("Tulane @ Duke", "total"): "2026-09-05",
    ("Oklahoma State @ Tulsa", "total"): "2026-09-05",
    ("Oklahoma State @ Tulsa", "spread"): "2026-09-05",
    ("Boston College @ Cincinnati", "total"): "2026-09-05",
}


def run(skip_confirm: bool = False):
    conn = get_conn()
    c = conn.cursor()

    print("Step 1: add predictions.game_date (TEXT, nullable) if it doesn't exist yet.")
    try:
        c.execute("ALTER TABLE predictions ADD COLUMN game_date TEXT")
        conn.commit()
        print("  Added.")
    except Exception as e:
        conn.rollback()
        print(f"  Skipped (likely already exists): {e}")

    c.execute("SELECT COUNT(*) as n FROM predictions WHERE game_date IS NULL")
    to_backfill = dict(c.fetchone())["n"]
    print(f"\nStep 2: backfill game_date = date for {to_backfill} row(s) with no game_date yet.")

    print("\nStep 3: correct the known-misdated CFB rows:")
    corrections = []
    for (game, market), correct_date in KNOWN_MISDATED_CFB_ROWS.items():
        c.execute(
            "SELECT id, game_date FROM predictions "
            "WHERE sport = 'cfb' AND date = '2026-09-03' AND game = ? AND market = ?",
            (game, market),
        )
        row = c.fetchone()
        if row:
            row = dict(row)
            corrections.append((row["id"], game, market, correct_date))
            print(f"  id={row['id']}  {game} [{market}]  ->  game_date={correct_date}")
        else:
            print(f"  NOT FOUND (already fixed, or row no longer exists): {game} [{market}]")

    if not skip_confirm:
        answer = input("\nApply these changes? Type YES to proceed: ").strip()
        if answer != "YES":
            print("Cancelled — nothing changed.")
            conn.close()
            return

    c.execute("UPDATE predictions SET game_date = date WHERE game_date IS NULL")
    backfilled = c.rowcount
    conn.commit()
    print(f"\nBackfilled game_date = date for {backfilled} row(s).")

    for pred_id, game, market, correct_date in corrections:
        c.execute("UPDATE predictions SET game_date = ? WHERE id = ?", (correct_date, pred_id))
    conn.commit()
    print(f"Corrected {len(corrections)} known-misdated CFB row(s).")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    run(skip_confirm=args.yes)
