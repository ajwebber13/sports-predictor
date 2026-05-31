"""
services/odds_parser.py
Fetches and parses live odds from The Odds API.
"""

import requests
import os

API_KEY = os.getenv("ODDS_API_KEY", "")
BASE_URL = "https://api.the-odds-api.com/v4"

SPORT_KEYS = {
    "nfl": "americanfootball_nfl",
    "ncaaf": "americanfootball_ncaaf",
    "nba": "basketball_nba",
    "ncaab": "basketball_ncaab",
    "wnba": "basketball_wnba",
}


def get_live_odds(sport="ncaaf"):
    """
    Fetch live spread + total odds for a given sport.
    sport: one of 'nfl', 'ncaaf', 'nba', 'ncaab'
    """
    sport_key = SPORT_KEYS.get(sport, sport)
    url = f"{BASE_URL}/sports/{sport_key}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "spreads,totals",
        "bookmakers": "draftkings,fanduel",
        "oddsFormat": "american",
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()


def parse_spread(game):
    """
    Extract spread outcomes from a game object.
    Returns list of {'name', 'point', 'price'} or None.
    """
    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "spreads":
                return market["outcomes"]
    return None


def parse_totals(game):
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
    """Convert American odds to implied probability."""
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)
