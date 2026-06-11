"""
services/odds_parser.py
Fetches and parses live odds from The Odds API.
"""

import requests
import os

API_KEY  = os.getenv("ODDS_API_KEY", "")
BASE_URL = "https://api.the-odds-api.com/v4"

SPORT_KEYS = {
    "nfl":   "americanfootball_nfl",
    "ncaaf": "americanfootball_ncaaf",
    "nba":   "basketball_nba",
    "ncaab": "basketball_ncaab",
    "ncaaw": "basketball_wncaab",
    "wnba":  "basketball_wnba",
}


def get_live_odds(sport: str = "nba") -> list:
    """
    Fetch moneyline odds for a given sport from The Odds API.
    Returns list of games with home_team, away_team, commence_time,
    event_id, and bookmakers (with moneyline markets).
    """
    sport_key = SPORT_KEYS.get(sport, sport)
    url       = f"{BASE_URL}/sports/{sport_key}/odds"
    params    = {
        "apiKey":      API_KEY,
        "regions":     "us",
        "markets":     "h2h,spreads,totals",  # h2h = moneyline
        "bookmakers":  "draftkings,fanduel",
        "oddsFormat":  "american",
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"Odds API error for {sport}: {e}")
        return []

    games = []
    for game in data:
        games.append({
            "home_team":     game.get("home_team", ""),
            "away_team":     game.get("away_team", ""),
            "commence_time": game.get("commence_time", ""),
            "event_id":      game.get("id", ""),
            "bookmakers":    game.get("bookmakers", []),
        })

    return games


def parse_moneyline(game: dict) -> dict:
    """
    Extract moneyline (h2h) implied probabilities for home and away teams.
    Averages across bookmakers for more accurate implied probability.
    Returns { home_team: implied_prob, away_team: implied_prob } or None.
    """
    home_team = game.get("home_team", "")
    away_team = game.get("away_team", "")

    home_probs = []
    away_probs = []

    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "h2h":
                for outcome in market.get("outcomes", []):
                    implied = american_to_implied(outcome["price"])
                    if outcome["name"] == home_team:
                        home_probs.append(implied)
                    elif outcome["name"] == away_team:
                        away_probs.append(implied)

    if not home_probs or not away_probs:
        return None

    # Average across bookmakers, then normalize to remove vig
    raw_home = sum(home_probs) / len(home_probs)
    raw_away = sum(away_probs) / len(away_probs)
    total    = raw_home + raw_away

    return {
        home_team: round((raw_home / total) * 100, 1),
        away_team: round((raw_away / total) * 100, 1),
    }


def parse_spread(game: dict):
    """
    Extract spread outcomes from a game object.
    Returns list of {'name', 'point', 'price'} or None.
    """
    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "spreads":
                return market["outcomes"]
    return None


def parse_totals(game: dict):
    """
    Extract over/under outcomes from a game object.
    Returns list of {'name', 'point', 'price'} or None.
    """
    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "totals":
                return market["outcomes"]
    return None


def american_to_implied(odds: int) -> float:
    """Convert American odds to implied probability (includes vig)."""
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)
