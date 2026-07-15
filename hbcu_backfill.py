"""
hbcu_backfill.py - Culture & Pulse Analytics
10-year historical backfill for HBCU sports: football, men's
basketball, women's basketball (MEAC + SWAC).

Pulls completed game results from ESPN's free team schedule
endpoint for each HBCU team, season by season, and stores them
in the head_to_head table tagged with sport keys:
  hbcu_football, hbcu_mbb, hbcu_wbb

Usage:
  python hbcu_backfill.py football        # backfill 10yrs of football
  python hbcu_backfill.py mbb              # backfill 10yrs of men's bball
  python hbcu_backfill.py wbb              # backfill 10yrs of women's bball
  python hbcu_backfill.py all              # backfill everything
"""

import requests
import time
from datetime import datetime
from database import get_conn, init_db
from hbcu_teams import HBCU_FOOTBALL_TEAMS, HBCU_MBB_TEAMS, HBCU_WBB_TEAMS

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

CURRENT_YEAR = datetime.now().year
YEARS_BACK   = 10

SPORT_PATHS = {
    "hbcu_football": "football/college-football",
    "hbcu_mbb":       "basketball/mens-college-basketball",
    "hbcu_wbb":       "basketball/womens-college-basketball",
}

SPORT_REGISTRIES = {
    "hbcu_football": HBCU_FOOTBALL_TEAMS,
    "hbcu_mbb":       HBCU_MBB_TEAMS,
    "hbcu_wbb":       HBCU_WBB_TEAMS,
}


def fetch_team_schedule(sport_key: str, team_id: str, season: int) -> list:
    """
    Pulls a team's full schedule for a given season from ESPN.
    Returns list of completed games with scores.
    """
    sport_path = SPORT_PATHS.get(sport_key)
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/teams/{team_id}/schedule"

    try:
        r = requests.get(url, headers=HEADERS, params={"season": season}, timeout=10)
        data = r.json()
    except Exception:
        return []

    games = []
    for event in data.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue
        comp = comps[0]
        status = comp.get("status", {}).get("type", {})
        if not status.get("completed"):
            continue

        competitors = comp.get("competitors", [])
        home = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue

        def get_score(c):
            score = c.get("score", 0)
            if isinstance(score, dict):
                return score.get("value", 0)
            try:
                return float(score)
            except (TypeError, ValueError):
                return 0

        home_team = home.get("team", {}).get("displayName", "")
        away_team = away.get("team", {}).get("displayName", "")
        home_score = get_score(home)
        away_score = get_score(away)
        date = event.get("date", "")[:10]

        if not home_team or not away_team or not date:
            continue

        winner = home_team if home_score > away_score else away_team

        games.append({
            "home_team": home_team,
            "away_team": away_team,
            "home_score": int(home_score),
            "away_score": int(away_score),
            "date": date,
            "winner": winner,
        })

    return games


def save_games(sport_key: str, games: list) -> int:
    """MIGRATION NOTE (2026-07-14): disabled, not converted.

    Same finding as the other head_to_head-dependent files in this
    migration: writes to a table confirmed to not exist in production.
    Unlike backfill.py and backfill_h2h_wnba.py, this one's error
    handling actually prints failures rather than swallowing them
    silently — meaning any real run of this script would have visibly
    spammed "no such table: head_to_head" errors, one per game, the
    whole time. Disabling rather than converting, same reasoning as
    the others: not inventing schema to catch up with a feature that
    never had a working data source."""
    print(f"    save_games() is disabled — head_to_head table was "
          f"never created in production.")
    return 0


def backfill_sport(sport_key: str):
    """MIGRATION NOTE (2026-07-14): disabled — depends entirely on
    save_games() above, which no longer writes anything. See that
    function's docstring."""
    print(f"  backfill_sport('{sport_key}') is disabled — depends on "
          f"the head_to_head table, which was never created in "
          f"production. See save_games()'s docstring for details.")
    return


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "football":
            backfill_sport("hbcu_football")
        elif arg == "mbb":
            backfill_sport("hbcu_mbb")
        elif arg == "wbb":
            backfill_sport("hbcu_wbb")
        elif arg == "all":
            backfill_sport("hbcu_football")
            backfill_sport("hbcu_mbb")
            backfill_sport("hbcu_wbb")
    else:
        print("Usage: python hbcu_backfill.py [football|mbb|wbb|all]")
