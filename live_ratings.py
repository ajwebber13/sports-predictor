"""
live_ratings.py — Culture & Pulse Analytics
Phase B: Live Net Ratings Fetcher

Pulls current net ratings automatically.
Replaces static tables in nba_wnba_predict.py.

Usage:
  python live_ratings.py           # fetch and display
  python live_ratings.py refresh   # force refresh cache

Requirements:
  pip install nba_api requests pandas
"""

import os
import json
import requests
from datetime import datetime, timedelta

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE    = os.path.join(BASE_DIR, "ratings_cache.json")
CACHE_TTL_HRS = 24


# ─────────────────────────────────────────────
# STATIC FALLBACK — used if all live sources fail
# ─────────────────────────────────────────────

NBA_STATIC = {
    "Oklahoma City Thunder": 11.1, "Detroit Pistons": 7.8,
    "Boston Celtics": 7.5, "San Antonio Spurs": 7.4,
    "New York Knicks": 7.0, "Denver Nuggets": 4.4,
    "Cleveland Cavaliers": 4.3, "Houston Rockets": 4.2,
    "Charlotte Hornets": 4.2, "Indiana Pacers": 3.1,
    "Golden State Warriors": 2.8, "Memphis Grizzlies": 2.1,
    "Los Angeles Lakers": 1.9, "Miami Heat": 1.4,
    "Minnesota Timberwolves": 0.8, "Philadelphia 76ers": 0.2,
    "Milwaukee Bucks": -0.3, "Atlanta Hawks": -0.8,
    "Dallas Mavericks": -1.1, "Sacramento Kings": -1.4,
    "Orlando Magic": -1.7, "Toronto Raptors": -2.2,
    "Brooklyn Nets": -2.9, "Los Angeles Clippers": -3.1,
    "New Orleans Pelicans": -3.8, "Chicago Bulls": -4.2,
    "Phoenix Suns": -4.9, "Utah Jazz": -7.1,
    "Portland Trail Blazers": -8.3, "Washington Wizards": -10.2,
}

WNBA_STATIC = {
    "Minnesota Lynx": 8.2, "Atlanta Dream": 5.1,
    "Dallas Wings": 4.8, "Indiana Fever": 3.9,
    "Portland Fire": 3.2, "Golden State Valkyries": 2.7,
    "Las Vegas Aces": 2.4, "Washington Mystics": 0.5,
    "Chicago Sky": -1.2, "Toronto Tempo": -1.8,
    "Los Angeles Sparks": -2.1, "Phoenix Mercury": -3.4,
    "Seattle Storm": -4.6, "New York Liberty": -5.2,
    "Connecticut Sun": -16.0,
}


# ─────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────

def load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    with open(CACHE_FILE, "r") as f:
        return json.load(f)

def save_cache(data: dict):
    data["cached_at"] = datetime.now().isoformat()
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def cache_is_fresh(cache: dict) -> bool:
    cached_at = cache.get("cached_at")
    if not cached_at:
        return False
    try:
        age = datetime.now() - datetime.fromisoformat(cached_at)
        return age < timedelta(hours=CACHE_TTL_HRS)
    except Exception:
        return False


# ─────────────────────────────────────────────
# NBA — via nba_api with correct parameters
# ─────────────────────────────────────────────

def fetch_nba_via_nba_api() -> dict:
    try:
        from nba_api.stats.endpoints import leaguedashteamstats

        # Use Base measure with PerGame — NET_RATING available in Advanced
        stats = leaguedashteamstats.LeagueDashTeamStats(
            season="2025-26",
            measure_type_detailed_defense="Advanced",
            per_mode_simple="PerGame",
            timeout=30,
        )
        df = stats.get_data_frames()[0]
        ratings = {}
        for _, row in df.iterrows():
            name = row.get("TEAM_NAME", "")
            net  = float(row.get("NET_RATING", 0.0))
            if name:
                ratings[name] = round(net, 1)
        return ratings
    except Exception:
        pass

    # Try alternate parameter name
    try:
        from nba_api.stats.endpoints import leaguedashteamstats
        stats = leaguedashteamstats.LeagueDashTeamStats(
            season="2025-26",
            measure_type_detailed_defense="Advanced",
            timeout=30,
        )
        df = stats.get_data_frames()[0]
        ratings = {}
        for _, row in df.iterrows():
            name = row.get("TEAM_NAME", "")
            net  = float(row.get("NET_RATING", 0.0))
            if name:
                ratings[name] = round(net, 1)
        return ratings
    except Exception as e:
        print(f"  [Ratings] nba_api error: {e}")
        return {}


# ─────────────────────────────────────────────
# NBA — direct NBA.com request (no package needed)
# ─────────────────────────────────────────────

def fetch_nba_direct() -> dict:
    try:
        url = "https://stats.nba.com/stats/leaguedashteamstats"
        headers = {
            "Host": "stats.nba.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "x-nba-stats-origin": "stats",
            "x-nba-stats-token": "true",
            "Referer": "https://www.nba.com/",
            "Connection": "keep-alive",
        }
        params = {
            "Season":       "2025-26",
            "SeasonType":   "Regular Season",
            "MeasureType":  "Advanced",
            "PerMode":      "PerGame",
            "LeagueID":     "00",
        }
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data    = resp.json()
        headers_list = data["resultSets"][0]["headers"]
        rows    = data["resultSets"][0]["rowSet"]

        name_idx = headers_list.index("TEAM_NAME")
        net_idx  = headers_list.index("NET_RATING")

        ratings = {}
        for row in rows:
            name = row[name_idx]
            net  = float(row[net_idx] or 0.0)
            ratings[name] = round(net, 1)

        return ratings
    except Exception as e:
        print(f"  [Ratings] NBA.com direct error: {e}")
        return {}


# ─────────────────────────────────────────────
# WNBA — ESPN standings point differential
# ─────────────────────────────────────────────

def fetch_wnba_live() -> dict:
    """
    Derive WNBA net ratings from Odds API market lines.
    Teams with stronger implied probabilities across games
    get higher net ratings. Uses current season static as base,
    adjusts based on recent odds data.
    """
    try:
        from intel_feed import ODDS_API_KEY
        if ODDS_API_KEY == "YOUR_ODDS_API_KEY_HERE":
            return {}

        resp = requests.get(
            "https://api.the-odds-api.com/v4/sports/basketball_wnba/odds",
            params={"apiKey": ODDS_API_KEY, "regions": "us",
                    "markets": "h2h", "oddsFormat": "american"},
            timeout=10
        )
        resp.raise_for_status()
        games = resp.json()
        if not games:
            return {}

        # Accumulate implied win prob per team across all games
        team_probs = {}
        team_counts = {}

        for game in games:
            for book in game.get("bookmakers", [])[:1]:
                for market in book.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        team  = outcome["name"]
                        odds  = outcome["price"]
                        if odds > 0:
                            prob = 100 / (odds + 100)
                        else:
                            prob = abs(odds) / (abs(odds) + 100)
                        team_probs[team]  = team_probs.get(team, 0) + prob
                        team_counts[team] = team_counts.get(team, 0) + 1

        if not team_probs:
            return {}

        # Convert avg implied prob to net rating scale
        # 50% implied = 0.0 net, 75% = +8.0, 25% = -8.0
        ratings = {}
        for team, total_prob in team_probs.items():
            avg_prob = total_prob / team_counts[team]
            net = round((avg_prob - 0.5) * 32, 1)  # scale to ~±16 range
            ratings[team] = net

        return ratings if len(ratings) >= 5 else {}

    except Exception as e:
        print(f"  [Ratings] WNBA Odds API error: {e}")
        return {}


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def get_live_ratings(league: str, force_refresh: bool = False) -> dict:
    cache     = load_cache()
    cache_key = f"{league}_ratings"

    if not force_refresh and cache_is_fresh(cache) and cache_key in cache:
        return cache[cache_key]

    print(f"  [Ratings] Fetching live {league} ratings...")

    if league == "NBA":
        ratings = fetch_nba_direct()
        if not ratings:
            ratings = fetch_nba_via_nba_api()
        if not ratings:
            print("  [Ratings] Live fetch failed — using static fallback.")
            return NBA_STATIC

    else:  # WNBA
        ratings = fetch_wnba_live()
        if not ratings:
            print("  [Ratings] WNBA live fetch failed — using static fallback.")
            return WNBA_STATIC

    print(f"  [Ratings] {len(ratings)} {league} teams loaded.")
    cache[cache_key] = ratings
    save_cache(cache)
    return ratings


# ─────────────────────────────────────────────
# STANDALONE
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    force = len(sys.argv) > 1 and sys.argv[1] == "refresh"

    for league in ["NBA", "WNBA"]:
        print(f"\n{'='*52}")
        print(f"  {league} NET RATINGS — {'LIVE' if force else 'Cached or Live'}")
        print(f"{'='*52}")

        ratings = get_live_ratings(league, force_refresh=force)
        sorted_r = sorted(ratings.items(), key=lambda x: x[1], reverse=True)

        for i, (team, rating) in enumerate(sorted_r, 1):
            sign = "+" if rating >= 0 else ""
            bar  = "█" * min(int(abs(rating)), 15)
            print(f"  {i:2}. {team:<32} {sign}{rating:.1f}  {bar}")
