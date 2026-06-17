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
    conn = get_conn()
    c    = conn.cursor()
    saved = 0

    for g in games:
        try:
            c.execute("""
                INSERT OR IGNORE INTO head_to_head
                (sport, season, date, home_team, away_team,
                 home_score, away_score, winner, game_type, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sport_key, str(g["date"][:4]), g["date"],
                g["home_team"], g["away_team"],
                g["home_score"], g["away_score"], g["winner"],
                "regular_season", "espn",
            ))
            if c.rowcount > 0:
                saved += 1
        except Exception as e:
            print(f"    Save error: {e}")

    conn.commit()
    conn.close()
    return saved


def backfill_sport(sport_key: str):
    """Runs the full 10-year backfill for one HBCU sport."""
    init_db()

    registry = SPORT_REGISTRIES.get(sport_key)
    if not registry:
        print(f"Unknown sport key: {sport_key}")
        return

    label = sport_key.replace("hbcu_", "").upper()
    print(f"\n{'='*60}")
    print(f"  HBCU {label} BACKFILL -- {YEARS_BACK} years, {len(registry)} teams")
    print(f"{'='*60}")

    total_games = 0
    seasons = range(CURRENT_YEAR - YEARS_BACK, CURRENT_YEAR + 1)

    for team_name, info in registry.items():
        team_id    = info["id"]
        team_games = 0

        for season in seasons:
            games = fetch_team_schedule(sport_key, team_id, season)
            if games:
                saved = save_games(sport_key, games)
                team_games += saved
            time.sleep(0.2)

        print(f"  {team_name:<38} {team_games} games saved")
        total_games += team_games

    print(f"\n{label} backfill complete: {total_games} total games saved")
    print(f"{'='*60}\n")


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
