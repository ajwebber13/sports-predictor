"""
services/odds_parser.py
Fetches live game data from ESPN's free public API.
No API key required. Replaces The Odds API.
"""

import requests

ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports"

SPORT_ENDPOINTS = {
    "nfl":   "football/nfl",
    "ncaaf": "football/college-football",
    "nba":   "basketball/nba",
    "ncaab": "basketball/mens-college-basketball",
    "wnba":  "basketball/wnba",
}


def get_live_odds(sport: str = "nba") -> list:
    endpoint = SPORT_ENDPOINTS.get(sport)
    if not endpoint:
        print(f"Unknown sport: {sport}")
        return []

    url = f"{ESPN_BASE}/{endpoint}/scoreboard"

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ESPN API error for {sport}: {e}")
        return []

    games = []
    for event in data.get("events", []):
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), "")
        away_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), "")
        game_time = event.get("date", "")

        if not home_team or not away_team:
            continue

        games.append({
            "home_team":     home_team,
            "away_team":     away_team,
            "commence_time": game_time,
            "event_id":      event.get("id", ""),
            "bookmakers":    [],
        })

    return games


def parse_spread(game):
    return None


def parse_totals(game):
    return None


def parse_moneyline(game):
    return None


def american_to_implied(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)
