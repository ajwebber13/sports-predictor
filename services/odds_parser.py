"""
services/odds_parser.py
Primary: The Odds API (real DraftKings/FanDuel lines)
Fallback: ESPN free API (no key needed)
Same output format for all downstream code.
"""
import requests
import os
from datetime import datetime, timezone, timedelta

CENTRAL_OFFSET = -5  # CDT
API_KEY        = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE  = "https://api.the-odds-api.com/v4"

ODDS_API_SPORT_KEYS = {
    "nfl":   "americanfootball_nfl",
    "ncaaf": "americanfootball_ncaaf",
    "nba":   "basketball_nba",
    "ncaab": "basketball_ncaab",
    "ncaaw": "basketball_wncaab",
    "wnba":  "basketball_wnba",
}

ESPN_ENDPOINTS = {
    "nfl":   "football/nfl",
    "ncaaf": "football/college-football",
    "nba":   "basketball/nba",
    "ncaab": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
    "wnba":  "basketball/wnba",
}

ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept":     "application/json",
    "Referer":    "https://www.espn.com/",
}


def _get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


# ── THE ODDS API (Primary) ───────────────────────────────────────────────

def get_odds_api(sport: str) -> list:
    """Pull live moneyline odds from The Odds API — DraftKings/FanDuel lines."""
    if not API_KEY:
        return []

    sport_key = ODDS_API_SPORT_KEYS.get(sport)
    if not sport_key:
        return []

    try:
        r = requests.get(
            f"{ODDS_API_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey":     API_KEY,
                "regions":    "us",
                "markets":    "h2h,spreads,totals",
                "bookmakers": "draftkings,fanduel",
                "oddsFormat": "american",
            },
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"Odds API error ({sport}): {e}")
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

    print(f"Odds API returned {len(games)} game(s) for {sport}")
    return games


# ── ESPN FALLBACK ────────────────────────────────────────────────────────

def get_espn_odds(sport: str) -> list:
    """Pull today's games from ESPN free API — fallback when Odds API unavailable."""
    endpoint = ESPN_ENDPOINTS.get(sport)
    if not endpoint:
        return []

    url      = f"{ESPN_BASE}/{endpoint}/scoreboard"
    today_ct = _get_today_ct()

    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ESPN fallback error ({sport}): {e}")
        return []

    games = []
    for event in data.get("events", []):
        try:
            game_date = event.get("date", "")
            if game_date:
                utc_dt     = datetime.fromisoformat(game_date.replace("Z", "+00:00"))
                central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
                if central_dt.date() != today_ct:
                    continue

            status = event.get("status", {}).get("type", {}).get("name", "")
            if any(x in status for x in ["Final", "STATUS_FINAL"]):
                continue

            comp        = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home = next((t for t in competitors if t["homeAway"] == "home"), None)
            away = next((t for t in competitors if t["homeAway"] == "away"), None)
            if not home or not away:
                continue

            home_name = home["team"]["displayName"]
            away_name = away["team"]["displayName"]

            odds_data  = comp.get("odds", [{}])
            odds_obj   = odds_data[0] if odds_data else {}
            home_ml    = odds_obj.get("homeTeamOdds", {}).get("moneyLine") or -110
            away_ml    = odds_obj.get("awayTeamOdds", {}).get("moneyLine") or -110
            spread     = odds_obj.get("spread", 0)
            over_under = odds_obj.get("overUnder", 0)

            games.append({
                "home_team":     home_name,
                "away_team":     away_name,
                "commence_time": game_date,
                "event_id":      event.get("id", ""),
                "bookmakers": [{
                    "key":     "espn",
                    "title":   "ESPN",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": home_name, "price": int(home_ml)},
                                {"name": away_name, "price": int(away_ml)},
                            ]
                        },
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": home_name, "point": spread, "price": -110},
                                {"name": away_name, "point": -spread if spread else 0, "price": -110},
                            ]
                        },
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over",  "point": over_under, "price": -110},
                                {"name": "Under", "point": over_under, "price": -110},
                            ]
                        },
                    ]
                }]
            })
        except Exception:
            continue

    print(f"ESPN fallback returned {len(games)} game(s) for {sport}")
    return games


# ── MAIN FUNCTION ────────────────────────────────────────────────────────

def get_live_odds(sport: str = "nba") -> list:
    """
    Primary: The Odds API (real DraftKings/FanDuel lines)
    Fallback: ESPN free API
    """
    # Try Odds API first
    if API_KEY:
        games = get_odds_api(sport)
        if games:
            return games
        print(f"  Odds API empty for {sport} — falling back to ESPN")

    # Fall back to ESPN
    return get_espn_odds(sport)


# ── HELPERS ──────────────────────────────────────────────────────────────

def parse_moneyline(game: dict) -> dict:
    home_team  = game.get("home_team", "")
    away_team  = game.get("away_team", "")
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

    raw_home = sum(home_probs) / len(home_probs)
    raw_away = sum(away_probs) / len(away_probs)
    total    = raw_home + raw_away

    return {
        home_team: round((raw_home / total) * 100, 1),
        away_team: round((raw_away / total) * 100, 1),
    }


def parse_spread(game: dict):
    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "spreads":
                return market["outcomes"]
    return None


def parse_totals(game: dict):
    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "totals":
                return market["outcomes"]
    return None


def american_to_implied(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)