"""
migrate_add_team_stats_cache_table.py — Culture & Pulse Analytics
=======================================================
One-time fix: nfl_data.py's get_team_stats() and cfb_data.py's
get_profile() only ever cached live ESPN team stats in-process
(_stats_cache), which resets to empty on every fresh Render deploy.
The 2026-09-11 incident: a deploy landed mid-run, wiped the cache, and
the next /nfl/edges call had to live-fetch all 32 NFL teams from ESPN
sequentially and uncached — a ~8 minute stall (see nfl_data.py's
2026-09-08 audit comment for the same failure mode observed earlier).

Adds one new table, shared by both NFL and CFB:
  team_stats_cache
    sport        TEXT — 'nfl' or 'cfb'
    team_name    TEXT — matches NFL_TEAM_IDS / FBS_TEAM_IDS keys
    cached_at    BIGINT — Unix epoch seconds, when this row was written.
                 Compared against TEAM_STATS_CACHE_TTL_SECONDS (6 hours)
                 in Python, not SQL — same reasoning as odds_api_cache.
    stats_json   TEXT — dataclasses.asdict(NFLTeamStats/CFBTeamStats) as JSON

PRIMARY KEY (sport, team_name) — one row per team per sport, upserted
on every real ESPN fetch (ON CONFLICT DO UPDATE in the app code).

Does NOT touch the in-process _stats_cache dicts in nfl_data.py or
cfb_data.py — those stay as a fast first-layer cache within a single
process; this table is the second layer that survives across
processes/deploys.

Usage:
    python migrate_add_team_stats_cache_table.py            # shows what it'll do, asks to confirm
    python migrate_add_team_stats_cache_table.py --yes      # skips the confirmation prompt
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

    print("This will create a new table:")
    print("  team_stats_cache (sport, team_name, cached_at, stats_json)")
    print("  PRIMARY KEY (sport, team_name)")

    if not skip_confirm:
        answer = input("\nApply this change? Type YES to proceed: ").strip()
        if answer != "YES":
            print("Cancelled — nothing changed.")
            conn.close()
            return

    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS team_stats_cache (
                sport       TEXT NOT NULL,
                team_name   TEXT NOT NULL,
                cached_at   BIGINT NOT NULL,
                stats_json  TEXT,
                PRIMARY KEY (sport, team_name)
            )
        """)
        conn.commit()
        print("  Created team_stats_cache.")
    except Exception as e:
        conn.rollback()
        print(f"  Skipped team_stats_cache (likely already exists): {e}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    run(skip_confirm=args.yes)
