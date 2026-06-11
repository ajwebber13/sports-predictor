"""
backfill_playoffs.py
=====================
Backfills 2025-26 NBA playoff box scores from first round through present.
Run once to seed your database with a full playoff season.

Usage:
  python backfill_playoffs.py              # NBA playoffs only
  python backfill_playoffs.py --all        # all sports current season
  python backfill_playoffs.py --sport wnba # specific sport
"""

import argparse
from datetime import datetime
from box_score_collector import backfill_sport, collect_games_for_date

# 2025-26 NBA Playoffs started April 19, 2026
# Backfill from April 19 through today
NBA_PLAYOFF_START = datetime(2026, 4, 19)

# Sport season start dates for full backfill
SEASON_STARTS = {
    "nba":   datetime(2025, 10, 22),  # Regular season start
    "wnba":  datetime(2026, 5, 16),   # WNBA season start
    "nfl":   datetime(2025, 9, 4),    # NFL season start
    "ncaaf": datetime(2025, 8, 23),   # CFB season start
    "ncaab": datetime(2025, 11, 4),   # NCAAB season start
    "ncaaw": datetime(2025, 11, 4),   # NCAAW season start
}


def days_since(start_date: datetime) -> int:
    return max(1, (datetime.now() - start_date).days + 1)


def backfill_nba_playoffs():
    """Backfill just the NBA playoff period."""
    days = days_since(NBA_PLAYOFF_START)
    print(f"Backfilling NBA playoffs ({days} days since Apr 19, 2026)...")
    backfill_sport("nba", days_back=days)


def backfill_full_season(sport: str):
    """Backfill entire current season for a sport."""
    start = SEASON_STARTS.get(sport)
    if not start:
        print(f"Unknown sport: {sport}")
        return
    days = days_since(start)
    print(f"Backfilling {sport} full season ({days} days)...")
    backfill_sport(sport, days_back=days)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default=None, help="Specific sport to backfill")
    parser.add_argument("--all",   action="store_true", help="Backfill all sports")
    parser.add_argument("--playoffs-only", action="store_true", help="NBA playoffs only (default)")
    args = parser.parse_args()

    if args.all:
        for sport in SEASON_STARTS:
            backfill_full_season(sport)
    elif args.sport:
        backfill_full_season(args.sport)
    else:
        # Default: NBA playoffs
        backfill_nba_playoffs()

    print("\n✅ Backfill complete.")
    print("Box scores saved to data/box_scores/")
    print("Run results_tracker.py to update prediction records.")
