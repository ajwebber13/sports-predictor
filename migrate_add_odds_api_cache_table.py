"""
migrate_add_odds_api_cache_table.py — Culture & Pulse Analytics
=======================================================
One-time fix: the Odds API fallback (services/odds_parser.py's
get_live_odds(), reached only when ESPN comes back empty) was only
ever cached in-process (_odds_cache), which resets on every fresh
render_job.py run. Render's cron jobs don't share memory or a
filesystem between runs, so every scheduled run, retry, and manual
trigger re-hit the Odds API from scratch for the same sport+date —
exactly what burned the account's 500 monthly credits down to zero
within days (see the 2026-09-09 OUT_OF_USAGE_CREDITS incident).

Adds one new table:
  odds_api_cache
    sport        TEXT — e.g. 'wnba', 'nfl', 'cfb'
    cache_date   TEXT — 'YYYY-MM-DD', Central time, the day this fetch
                 is for (NOT when it was cached — see cached_at)
    cached_at    BIGINT — Unix epoch seconds, when this row was written.
                 Compared against ODDS_API_CACHE_TTL_SECONDS (2 hours)
                 in Python, not SQL, so this works identically across
                 Postgres/Turso/SQLite without any DB-side date math.
    games_json   TEXT — the raw games list from get_odds_api(), as JSON

PRIMARY KEY (sport, cache_date) — one row per sport per day, upserted
on every real fetch (ON CONFLICT DO UPDATE in the app code).

Does NOT touch _odds_cache or the ESPN-primary path at all — ESPN is
free, so its existing in-memory-only cache is unchanged.

Usage:
    python migrate_add_odds_api_cache_table.py            # shows what it'll do, asks to confirm
    python migrate_add_odds_api_cache_table.py --yes      # skips the confirmation prompt
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
    print("  odds_api_cache (sport, cache_date, cached_at, games_json)")
    print("  PRIMARY KEY (sport, cache_date)")

    if not skip_confirm:
        answer = input("\nApply this change? Type YES to proceed: ").strip()
        if answer != "YES":
            print("Cancelled — nothing changed.")
            conn.close()
            return

    try:
        c.execute("""
            CREATE TABLE IF NOT EXISTS odds_api_cache (
                sport       TEXT NOT NULL,
                cache_date  TEXT NOT NULL,
                cached_at   BIGINT NOT NULL,
                games_json  TEXT,
                PRIMARY KEY (sport, cache_date)
            )
        """)
        conn.commit()
        print("  Created odds_api_cache.")
    except Exception as e:
        conn.rollback()
        print(f"  Skipped odds_api_cache (likely already exists): {e}")

    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    run(skip_confirm=args.yes)
