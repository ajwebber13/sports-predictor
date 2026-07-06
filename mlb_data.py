"""
mlb_data.py
Live MLB data pipeline — mirrors cfb_data.py / nfl_data.py pattern.
"""

import requests
from datetime import datetime, timedelta

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
ESPN_TEAM_STATS_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{team_id}/statistics"

# TODO: fill in all 30 team ESPN IDs (same pattern as NFL_TEAM_IDS)
# Get these from ESPN's team list endpoint or team page URLs
MLB_TEAM_IDS = {
    "Yankees": 10,
    "Red Sox": 2,
    "Dodgers": 19,
    # ... fill in remaining 27 teams
}

# League-average flat defaults — used only when ESPN returns nothing at all
FLAT_DEFAULTS = {
    "runs_per_game": 4.5,
    "era": 4.20,
    "whip": 1.30,
    "batting_avg": 0.250,
}


def get_mlb_events(days_window=1):
    """
    Pull MLB games for today (or a window, for scheduling flexibility).
    MLB is daily like WNBA, not weekly like CFB/NFL.
    """
    games = []
    for offset in range(days_window):
        date = (datetime.utcnow() + timedelta(days=offset)).strftime("%Y%m%d")
        resp = requests.get(ESPN_SCOREBOARD_URL, params={"dates": date})
        resp.raise_for_status()
        data = resp.json()
        for event in data.get("events", []):
            games.append(event)
    return games


def get_team_stats(team_name, season=None):
    """
    Fetch team stats, gated on whether stat categories exist —
    NOT on win/loss record (ESPN's record endpoint is unreliable,
    confirmed during the CFB build).
    """
    team_id = MLB_TEAM_IDS.get(team_name)
    if team_id is None:
        return _flat_defaults()

    params = {"season": season} if season else {}
    resp = requests.get(ESPN_TEAM_STATS_URL.format(team_id=team_id), params=params)

    if resp.status_code != 200:
        return _flat_defaults()

    data = resp.json()
    categories = data.get("results", {}).get("stats", {}).get("categories", [])

    if not categories:
        return _flat_defaults()

    # TODO: parse actual stat category names once we see real ESPN response —
    # MLB stat keys differ from NFL/CFB (confirmed pattern: always verify
    # actual key names against a live API call before trusting field names)
    stats = _parse_stat_categories(categories)

    # Sanity clamps — same defensive pattern as CFB/NFL
    if stats["runs_per_game"] > 12 or stats["runs_per_game"] <= 0:
        stats["runs_per_game"] = FLAT_DEFAULTS["runs_per_game"]
    if stats["era"] > 9 or stats["era"] <= 0:
        stats["era"] = FLAT_DEFAULTS["era"]

    return stats


def _parse_stat_categories(categories):
    """Placeholder — fill in once we confirm real ESPN key names."""
    return dict(FLAT_DEFAULTS)


def _flat_defaults():
    return dict(FLAT_DEFAULTS)


def get_starting_pitcher(event):
    """
    NEW for MLB — no equivalent in CFB/NFL/WNBA.
    ESPN scoreboard events include probable pitcher data under
    competitions[0].competitors[].probables — needs live-response
    confirmation before trusting the exact path.
    """
    try:
        competitors = event["competitions"][0].get("probables", [])
        return competitors  # list of {athlete, statistics} per side
    except (KeyError, IndexError):
        return []


def get_pitcher_stats(pitcher_id, season=None):
    """
    Fetch a starting pitcher's ERA, WHIP, K/9, recent form.
    This is the new signal MLB needs that other sports don't —
    a single player who dominates the day's outcome more than any
    one player does in football/basketball.
    """
    # TODO: ESPN athlete stats endpoint —
    # https://site.api.espn.com/apis/common/v3/sports/baseball/mlb/athletes/{pitcher_id}/stats
    pass