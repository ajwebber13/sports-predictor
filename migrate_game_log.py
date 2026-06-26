"""
migrate_game_log.py — Culture & Pulse Analytics
One-time migration: adds opponent and home_away columns to wnba_game_log,
then backfills opponent for dates with only 2 teams (unambiguous pairs).

Run once:
    python migrate_game_log.py
"""

import sqlite3
import os
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), "cp_analytics.db")


def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. Add columns (safe to re-run — ignores if already exists)
    for col, coltype in [("opponent", "TEXT"), ("home_away", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE wnba_game_log ADD COLUMN {col} {coltype}")
            print(f"  Added column: {col}")
        except sqlite3.OperationalError:
            print(f"  Column already exists: {col}")

    # 2. Backfill opponent for 2-team dates (1 game — unambiguous)
    c.execute("SELECT DISTINCT date, team_name FROM wnba_game_log ORDER BY date")
    by_date = defaultdict(list)
    for r in c.fetchall():
        by_date[r["date"]].append(r["team_name"])

    patched = 0
    skipped = 0
    for date, teams in by_date.items():
        if len(teams) == 2:
            t1, t2 = teams[0], teams[1]
            c.execute(
                "UPDATE wnba_game_log SET opponent = ? WHERE date = ? AND team_name = ? AND opponent IS NULL",
                (t2, date, t1)
            )
            c.execute(
                "UPDATE wnba_game_log SET opponent = ? WHERE date = ? AND team_name = ? AND opponent IS NULL",
                (t1, date, t2)
            )
            patched += 2
        else:
            skipped += len(teams)

    conn.commit()

    # 3. Summary
    c.execute("SELECT COUNT(*) FROM wnba_game_log WHERE opponent IS NOT NULL")
    with_opp = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM wnba_game_log WHERE opponent IS NULL")
    without_opp = c.fetchone()[0]

    print(f"\n  Patched:  {patched} rows")
    print(f"  Skipped:  {skipped} rows (multi-game dates — will populate going forward)")
    print(f"  With opponent:    {with_opp}")
    print(f"  Without opponent: {without_opp}")
    print("\n  Migration complete. prop_hit_rates.py is ready to use.")

    conn.close()


if __name__ == "__main__":
    run()
