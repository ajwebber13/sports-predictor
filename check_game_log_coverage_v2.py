"""
check_game_log_coverage_v2.py - Culture & Pulse Analytics

Generalized version of check_game_log_coverage.py — takes a table name
so it can audit any sport's *_game_log table before building a
<sport>_game_results.py derivation module for it, same discipline
used for WNBA (2026-07-11): verify real coverage before writing code
that assumes it.

Usage:
    python check_game_log_coverage_v2.py nba_game_log
"""

import sys
from database import get_conn


def run(table: str):
    conn = get_conn()
    c = conn.cursor()

    print("=" * 70)
    print(f"1. {table} overview")
    print("=" * 70)
    try:
        c.execute(f"""
            SELECT COUNT(*) AS total_rows,
                   COUNT(DISTINCT date) AS distinct_dates,
                   COUNT(DISTINCT team_name) AS distinct_teams,
                   MIN(date) AS earliest,
                   MAX(date) AS latest
            FROM {table}
        """)
    except Exception as e:
        print(f"  ERROR: {e}")
        conn.close()
        return
    row = dict(c.fetchone())
    for k, v in row.items():
        print(f"  {k}: {v}")

    if not row["total_rows"]:
        print(f"\n  {table} is EMPTY. No derivation possible until this table has real data.")
        conn.close()
        return

    print()
    print("=" * 70)
    print("2. most recent 10 game-dates")
    print("=" * 70)
    c.execute(f"""
        SELECT date, COUNT(DISTINCT team_name) AS teams_on_date
        FROM {table}
        GROUP BY date
        ORDER BY date DESC
        LIMIT 10
    """)
    for r in c.fetchall():
        d = dict(r)
        print(f"  {d['date']:<12} teams={d['teams_on_date']}")

    conn.close()
    print()
    print("=" * 70)
    print("What to look for: is 'latest' recent, or is this table stale/offseason-only?")
    print("=" * 70)


if __name__ == "__main__":
    table = sys.argv[1] if len(sys.argv) > 1 else "nba_game_log"
    run(table)
