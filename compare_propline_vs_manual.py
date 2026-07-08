"""
compare_propline_vs_manual.py — Culture & Pulse Analytics
============================================================
Pulls today's (or a specified date's) player props from PropLine and
diffs them against whatever's already in player_props with source='manual'
for that same date. Tells you:
  - which manual players/stats PropLine also covers (safe to trust automated)
  - which manual players/stats PropLine is MISSING (real gap — automated
    run will silently drop these unless you keep a manual fallback for them)
  - which players PropLine has that you didn't manually cover (bonus coverage)

Does NOT write to the database. Read-only comparison, safe to run anytime.

Usage:
    python compare_propline_vs_manual.py                    # today
    python compare_propline_vs_manual.py --date 2026-07-02  # specific date
"""

import os
import sqlite3
import argparse
from datetime import datetime, timezone, timedelta

from fetch_prizepicks_props import fetch_props_for_sport

DB_PATH = os.path.join(os.path.dirname(__file__), "cp_analytics.db")


def get_today_ct() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=-5)).strftime("%Y-%m-%d")


def get_manual_props(date_str: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT player_name, stat, line
        FROM player_props
        WHERE date = ? AND source = 'manual'
    """, (date_str,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Date to compare (default: today CT)")
    args = parser.parse_args()

    date_str = args.date or get_today_ct()
    print(f"Comparing PropLine vs manual props for {date_str}\n")

    manual_rows = get_manual_props(date_str)
    manual_set  = {(r["player_name"], r["stat"]) for r in manual_rows}
    print(f"Manual entries for {date_str}: {len(manual_set)} player/stat combos")

    print("\nFetching live PropLine data for WNBA...")
    propline_props = fetch_props_for_sport("wnba", target_date=date_str)
    propline_set = {(p["player_name"], p["stat"]) for p in propline_props}
    print(f"PropLine entries: {len(propline_set)} player/stat combos\n")

    if not propline_set:
        print("PropLine returned nothing — either no games today, API key issue, or no lines posted yet.")
        print("Nothing to compare. Try again closer to game time or check PROPLINE_API_KEY.")
        return

    matched      = manual_set & propline_set
    manual_only  = manual_set - propline_set   # real gap — automated run won't have these
    propline_only = propline_set - manual_set  # bonus — PropLine covers players you didn't

    print("=" * 60)
    print(f"MATCHED ({len(matched)}) — PropLine covers these, safe to rely on automated:")
    for player, stat in sorted(matched):
        print(f"  ✅ {player} — {stat}")

    print()
    print(f"GAP — in your manual list but PropLine does NOT have ({len(manual_only)}):")
    if not manual_only:
        print("  None — full coverage.")
    for player, stat in sorted(manual_only):
        print(f"  ⚠️  {player} — {stat}")

    print()
    print(f"BONUS — PropLine has these, not in your manual list ({len(propline_only)}):")
    if not propline_only:
        print("  None.")
    for player, stat in sorted(propline_only):
        print(f"  ➕ {player} — {stat}")
    print("=" * 60)


if __name__ == "__main__":
    main()
