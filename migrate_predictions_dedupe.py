"""
migrate_predictions_dedupe.py — Culture & Pulse Analytics
===========================================================
One-time fix for a real bug: predictions had UNIQUE(date, sport, game, bet)
instead of UNIQUE(date, sport, game) — meaning if two pipeline runs on the
same day picked different sides of the same game (market moved, or an old
version of the edge-selection logic flipped which side "won"), BOTH got
saved as separate rows instead of one replacing the other. That's why you
saw both "Portland Fire ML" and "Las Vegas Aces ML" for the same game on
the dashboard.

This script:
1. Finds every (date, sport, game) with more than one prediction row.
2. For each duplicate group, keeps the row a scored result already points
   to (if the game's already been played) — otherwise keeps the most
   recent run. Never orphans an already-scored result.
3. Recreates the predictions table with the correct UNIQUE(date, sport, game)
   constraint, preserving every row's original id (so any existing
   results.prediction_id references stay valid) and fixing the
   autoincrement counter afterward.

Run this once. After it's applied, log_prediction() in database.py uses
INSERT OR REPLACE against the corrected constraint, so a later run for the
same game correctly replaces the earlier pick instead of duplicating it.

Usage:
    python migrate_predictions_dedupe.py            # shows what it'll do, asks to confirm
    python migrate_predictions_dedupe.py --yes       # skips the confirmation prompt
"""

import argparse
import sys

sys.path.insert(0, ".")
from database import get_conn


def run(skip_confirm: bool = False):
    conn = get_conn()
    c = conn.cursor()

    dupes = c.execute("""
        SELECT date, sport, game, COUNT(*) as cnt
        FROM predictions GROUP BY date, sport, game HAVING cnt > 1
    """).fetchall()

    if not dupes:
        print("No duplicate (date, sport, game) predictions found — nothing to dedupe.")
    else:
        print(f"\n  Found {len(dupes)} game(s) with duplicate predictions:\n")
        for row in dupes:
            date, sport, game, cnt = row[0], row[1], row[2], row[3]
            print(f"    {date}  {sport:6s}  {game}  ({cnt} rows)")
        print()

    print("  This will also recreate the predictions table with a corrected")
    print("  UNIQUE(date, sport, game) constraint (currently includes 'bet' too,")
    print("  which is the root cause). Row ids are preserved — results table")
    print("  references stay intact.\n")

    if not skip_confirm:
        answer = input("  Type YES to proceed: ").strip()
        if answer != "YES":
            print("  Cancelled — nothing changed.")
            conn.close()
            return

    removed = 0
    for row in dupes:
        date, sport, game = row[0], row[1], row[2]
        ids = [r[0] for r in c.execute(
            "SELECT id FROM predictions WHERE date=? AND sport=? AND game=?",
            (date, sport, game)
        ).fetchall()]

        result_row = c.execute(
            "SELECT prediction_id FROM results WHERE date=? AND sport=? AND game=?",
            (date, sport, game)
        ).fetchone()

        if result_row and result_row[0] in ids:
            keep_id = result_row[0]
        else:
            keep_id = max(ids)

        drop_ids = [i for i in ids if i != keep_id]
        for did in drop_ids:
            c.execute("DELETE FROM predictions WHERE id=?", (did,))
            removed += 1

    conn.commit()
    print(f"  Removed {removed} duplicate row(s), kept the correct pick for each game.")

    # ---- recreate the table with the corrected constraint, preserving ids ----
    print("  Recreating predictions table with UNIQUE(date, sport, game)...")
    c.execute("ALTER TABLE predictions RENAME TO predictions_old")
    c.execute("""
        CREATE TABLE predictions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            sport           TEXT NOT NULL,
            game            TEXT NOT NULL,
            home_team       TEXT NOT NULL,
            away_team       TEXT NOT NULL,
            bet             TEXT NOT NULL,
            odds            INTEGER,
            model_prob      REAL,
            implied_prob    REAL,
            edge            REAL,
            home_record     TEXT,
            away_record     TEXT,
            home_rest       INTEGER,
            away_rest       INTEGER,
            home_injuries   TEXT,
            away_injuries   TEXT,
            game_type       TEXT DEFAULT 'regular_season',
            predicted_winner TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport, game)
        )
    """)
    c.execute("INSERT INTO predictions SELECT * FROM predictions_old")
    c.execute("INSERT OR REPLACE INTO sqlite_sequence (name, seq) SELECT 'predictions', MAX(id) FROM predictions")
    c.execute("DROP TABLE predictions_old")
    conn.commit()

    final_count = c.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    print(f"  Done. predictions table now has {final_count} rows, one per game per day, ids preserved.")
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    run(skip_confirm=args.yes)
