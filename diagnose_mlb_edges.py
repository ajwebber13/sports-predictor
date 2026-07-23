"""
Quick read-only diagnostic — run this from the same folder as edge_finder.py.
Doesn't change anything, just shows what's actually in player_props for
MLB on the given date, before any Edge Finder filtering.

Usage:
    python diagnose_mlb_edges.py --date 2026-07-22
"""
import argparse
import os
from dotenv import load_dotenv
load_dotenv()

from database import get_conn

parser = argparse.ArgumentParser()
parser.add_argument("--date", required=True)
args = parser.parse_args()

conn = get_conn()
c = conn.cursor()

c.execute("SELECT COUNT(*) FROM player_props WHERE date = ? AND sport = 'mlb'", (args.date,))
total = c.fetchone()[0]
print(f"Total MLB props on {args.date}: {total}")

if total == 0:
    print("No MLB props exist for this date at all — check whether the fetch pipeline ran for MLB today.")
else:
    c.execute("""
        SELECT stat, COUNT(*) as n,
               SUM(CASE WHEN hit_rate_overall IS NULL THEN 1 ELSE 0 END) as null_hit_rate,
               SUM(CASE WHEN games_overall IS NULL THEN 1 ELSE 0 END) as null_games,
               SUM(CASE WHEN defense_factor IS NULL THEN 1 ELSE 0 END) as null_defense,
               SUM(CASE WHEN projection_edge_pct IS NULL THEN 1 ELSE 0 END) as null_edge_pct
        FROM player_props
        WHERE date = ? AND sport = 'mlb'
        GROUP BY stat
        ORDER BY n DESC
    """, (args.date,))
    rows = c.fetchall()
    print(f"\n{'STAT':<15}{'COUNT':<8}{'NULL hit_rate':<16}{'NULL games':<13}{'NULL defense':<15}{'NULL edge_pct':<15}")
    for r in rows:
        print(f"{r[0]:<15}{r[1]:<8}{r[2]:<16}{r[3]:<13}{r[4]:<15}{r[5]:<15}")

    print("\nIf a stat's NULL counts equal its total count, every prop for that")
    print("stat is being excluded from Edge Finder before scoring even happens —")
    print("regardless of the 65% hit rate / 5% edge / 10-game guardrails.")

conn.close()
