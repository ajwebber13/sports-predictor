"""
services/odds_parser.py
Fetches live odds from ESPN free API — no API key needed.
Replaces The Odds API. Same output format, all sports supported.
"""
import requests
from datetime import datetime, timezone, timedelta

CENTRAL_OFFSET = -5  # CDT

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
    "Accept": "application/json",
    "Referer": "https://www.espn.com/",
}


def _get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def get_live_odds(sport: str = "nba") -> list:
    """
    Fetch today's games with moneyline odds from ESPN free API.
    Returns same format as The Odds API so all downstream code works unchanged.
    """
    endpoint = ESPN_ENDPOINTS.get(sport)
    if not endpoint:
        print(f"Unknown sport: {sport}")
        return []

    url = f"{ESPN_BASE}/{endpoint}/scoreboard"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ESPN odds fetch error ({sport}): {e}")
        return []

    today_ct = _get_today_ct()
    games    = []

    for event in data.get("events", []):
        try:
            # Date filter — today only
            game_date = event.get("date", "")
            if game_date:
                utc_dt     = datetime.fromisoformat(game_date.replace("Z", "+00:00"))
                central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
                if central_dt.date() != today_ct:
                    continue

            # Skip completed games
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

            # Pull moneyline odds from ESPN
            odds_data = comp.get("odds", [{}])
            odds_obj  = odds_data[0] if odds_data else {}
            home_ml   = odds_obj.get("homeTeamOdds", {}).get("moneyLine") or -110
            away_ml   = odds_obj.get("awayTeamOdds", {}).get("moneyLine") or -110
            spread    = odds_obj.get("spread", 0)
            over_under = odds_obj.get("overUnder", 0)

            # Format to match Odds API structure exactly
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
                                {"name": home_name, "point": spread,         "price": -110},
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

        except Exception as e:
            print(f"  Parse error: {e}")
            continue

    print(f"ESPN returned {len(games)} game(s) for {sport}")
    return games


def parse_moneyline(game: dict) -> dict:
    """
    Extract moneyline implied probabilities.
    Returns { home_team: implied_prob, away_team: implied_prob } or None.
    """
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