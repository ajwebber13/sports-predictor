"""
backfill_h2h_wnba.py — Culture & Pulse Analytics
=================================================
Fixes the WNBA head-to-head data gap caused by the 1st/15th
sampling approach in backfill.py.

Pulls every day of every WNBA season (May-October) from ESPN
and loads all completed games into head_to_head table.

A real WNBA season has ~180 league-wide games. The old approach
only captured ~15-20 per season. This fixes that.

Usage:
  python backfill_h2h_wnba.py           # all seasons 2016-2026
  python backfill_h2h_wnba.py 2025      # specific season only
  python backfill_h2h_wnba.py 2025 2026 # range
"""

import sys
import time
import requests
from datetime import datetime, timedelta
from database import get_conn

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"

# WNBA regular season runs May through September
# Playoffs push into October
SEASON_START_MONTH = 5   # May
SEASON_END_MONTH   = 10  # October


def date_range(year: int):
    """Yields every date in the WNBA season for a given year."""
    start = datetime(year, SEASON_START_MONTH, 1)
    end   = datetime(year, SEASON_END_MONTH, 31) if year < datetime.now().year \
            else datetime.now()
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def fetch_wnba_games_for_date(date: datetime) -> list:
    """Fetch all completed WNBA games from ESPN for a specific date."""
    date_str = date.strftime("%Y%m%d")
    try:
        r    = requests.get(ESPN_URL, params={"dates": date_str},
                            headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        return []

    games = []
    for event in data.get("events", []):
        completed = event.get("status", {}).get("type", {}).get("completed", False)
        if not completed:
            continue

        comp        = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        home = next((t for t in competitors if t.get("homeAway") == "home"), None)
        away = next((t for t in competitors if t.get("homeAway") == "away"), None)

        if not home or not away:
            continue

        home_name  = home["team"]["displayName"]
        away_name  = away["team"]["displayName"]
        home_score = int(home.get("score", 0) or 0)
        away_score = int(away.get("score", 0) or 0)

        if home_score == 0 and away_score == 0:
            continue  # skip games with no scores

        winner    = home_name if home_score > away_score else away_name
        game_date = event.get("date", "")[:10]

        # Detect game type from season info
        season_type = event.get("season", {}).get("type", 2)
        game_type   = {1: "preseason", 2: "regular_season",
                       3: "playoff", 4: "offseason"}.get(season_type, "regular_season")

        games.append({
            "home_team":  home_name,
            "away_team":  away_name,
            "home_score": home_score,
            "away_score": away_score,
            "winner":     winner,
            "date":       game_date,
            "game_type":  game_type,
        })

    return games


def backfill_wnba_h2h(start_year: int = 2016, end_year: int = None):
    """MIGRATION NOTE (2026-07-14): disabled, not converted.

    Same finding as backfill.py's backfill_head_to_head() and
    home_away_splits.py's build_splits(): this writes to head_to_head,
    confirmed to not exist in the live Turso database. Every INSERT
    here has always been failing silently, caught by the bare
    `except Exception as e: pass` inside the loop — this script has
    never saved a single record despite its year-by-year progress
    output implying otherwise.

    Not converting this to Postgres syntax, since doing so would make
    it actually start writing to a table that doesn't exist in
    schema_postgres.sql either — same "don't invent schema to catch up
    with dead code" reasoning as the other two head_to_head-dependent
    functions. Kept as _unused_backfill_wnba_h2h() below since its
    day-by-day approach is a real improvement over backfill.py's old
    1st/15th sampling — worth reusing if head-to-head tracking gets
    built as a real feature later."""
    print(f"  backfill_wnba_h2h() is disabled — depends on the "
          f"head_to_head table, which was never created in production.")
    return


def _unused_backfill_wnba_h2h(start_year: int = 2016, end_year: int = None):
    """
    Pull all WNBA games for every day of every season
    and load into head_to_head table.
    """
    if end_year is None:
        end_year = datetime.now().year

    conn  = get_conn()
    c     = conn.cursor()

    total_saved  = 0
    total_exists = 0

    for year in range(start_year, end_year + 1):
        year_saved = 0
        print(f"  WNBA {year}...", end="", flush=True)

        for date in date_range(year):
            games = fetch_wnba_games_for_date(date)

            for g in games:
                try:
                    c.execute("""
                        INSERT INTO head_to_head
                        (sport, season, date, home_team, away_team,
                         home_score, away_score, winner, game_type, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                    """, (
                        "wnba", str(year), g["date"],
                        g["home_team"], g["away_team"],
                        g["home_score"], g["away_score"],
                        g["winner"], g["game_type"], "espn_full"
                    ))
                    if c.rowcount > 0:
                        year_saved += 1
                except Exception as e:
                    conn.rollback()

            # Light rate limiting — ESPN free API
            time.sleep(0.3)

        conn.commit()
        total_saved += year_saved
        print(f" {year_saved} games saved")

    conn.close()

    print(f"\n  ✅ WNBA head-to-head complete: {total_saved} new records saved")
    print(f"  Run: python elo_ratings.py backfill wnba")
    print(f"  Then: python backtest_engine.py wnba\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) == 0:
        backfill_wnba_h2h(2016, datetime.now().year)
    elif len(args) == 1:
        backfill_wnba_h2h(int(args[0]), int(args[0]))
    elif len(args) == 2:
        backfill_wnba_h2h(int(args[0]), int(args[1]))
    else:
        print("Usage: python backfill_h2h_wnba.py [start_year] [end_year]")
