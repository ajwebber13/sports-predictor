"""
mlb_data.py
Live MLB data pipeline — mirrors cfb_data.py / nfl_data.py pattern.
"""

import requests
from datetime import datetime, timedelta, timezone

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
ESPN_TEAM_STATS_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{team_id}/statistics"

MLB_TEAM_IDS = {
    "Arizona Diamondbacks": 29,
    "Athletics": 11,
    "Atlanta Braves": 15,
    "Baltimore Orioles": 1,
    "Boston Red Sox": 2,
    "Chicago Cubs": 16,
    "Chicago White Sox": 4,
    "Cincinnati Reds": 17,
    "Cleveland Guardians": 5,
    "Colorado Rockies": 27,
    "Detroit Tigers": 6,
    "Houston Astros": 18,
    "Kansas City Royals": 7,
    "Los Angeles Angels": 3,
    "Los Angeles Dodgers": 19,
    "Miami Marlins": 28,
    "Milwaukee Brewers": 8,
    "Minnesota Twins": 9,
    "New York Mets": 21,
    "New York Yankees": 10,
    "Philadelphia Phillies": 22,
    "Pittsburgh Pirates": 23,
    "San Diego Padres": 25,
    "San Francisco Giants": 26,
    "Seattle Mariners": 12,
    "St. Louis Cardinals": 24,
    "Tampa Bay Rays": 30,
    "Texas Rangers": 13,
    "Toronto Blue Jays": 14,
    "Washington Nationals": 20,
}

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
    games.sort(key=lambda e: e.get("date", ""))  # chronological — ensures DH Game 1 comes before Game 2
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
    categories = data.get("splits", [])

    if not categories:
        return _flat_defaults()

    stats = _parse_stat_categories(categories)

    if stats["runs_per_game"] > 12 or stats["runs_per_game"] <= 0:
        stats["runs_per_game"] = FLAT_DEFAULTS["runs_per_game"]
    if stats["era"] > 9 or stats["era"] <= 0:
        stats["era"] = FLAT_DEFAULTS["era"]

    return stats


def _parse_stat_categories(categories):
    """
    Pulls team-level runs/game and ERA from the ESPN statistics response.
    ESPN returns multiple splits (batting order slots, Pre/Post All-Star, etc.) —
    the real team totals are the split with the highest at-bats count, not
    any specific named split (label changes after the All-Star break).
    """
    best_split = None
    best_atbats = -1

    for split in categories:
        for cat in split.get("categories", []):
            if cat["name"] != "batting":
                continue
            stats = {s["name"]: s["value"] for s in cat["stats"]}
            atbats = stats.get("atBats", 0)
            if atbats > best_atbats:
                best_atbats = atbats
                best_split = split

    if not best_split:
        return dict(FLAT_DEFAULTS)

    batting_stats = {}
    pitching_stats = {}
    for cat in best_split.get("categories", []):
        stats = {s["name"]: s["value"] for s in cat["stats"]}
        if cat["name"] == "batting":
            batting_stats = stats
        elif cat["name"] == "pitching":
            pitching_stats = stats

    games = batting_stats.get("teamGamesPlayed", 1)
    runs = batting_stats.get("runs", games * FLAT_DEFAULTS["runs_per_game"])

    return {
        "runs_per_game": round(runs / games, 2) if games else FLAT_DEFAULTS["runs_per_game"],
        "era": pitching_stats.get("ERA", FLAT_DEFAULTS["era"]),
        "whip": pitching_stats.get("WHIP", FLAT_DEFAULTS["whip"]),
        "batting_avg": batting_stats.get("avg", FLAT_DEFAULTS["batting_avg"]),
    }


def _flat_defaults():
    return dict(FLAT_DEFAULTS)


def get_starting_pitcher(event):
    """
    Starting pitcher data lives inside each COMPETITOR, not at the
    top level of the competition — confirmed via live API check.
    Returns {"home": probable_dict_or_None, "away": probable_dict_or_None}
    """
    result = {"home": None, "away": None}
    try:
        competitors = event["competitions"][0]["competitors"]
        for comp in competitors:
            side = comp.get("homeAway")
            probables = comp.get("probables", [])
            if probables:
                result[side] = probables[0]
    except (KeyError, IndexError):
        pass
    return result


def get_pitcher_stats(probable):
    """
    ESPN embeds the pitcher's ERA and WHIP directly in the scoreboard's
    probables data — no separate athlete-stats API call needed.
    """
    if not probable:
        return {"era": FLAT_DEFAULTS["era"], "whip": FLAT_DEFAULTS["whip"]}

    stats = {s["name"]: s.get("displayValue") for s in probable.get("statistics", [])}

    try:
        era = float(stats.get("ERA"))
    except (TypeError, ValueError):
        era = FLAT_DEFAULTS["era"]

    try:
        whip = float(stats.get("WHIP"))
    except (TypeError, ValueError):
        whip = FLAT_DEFAULTS["whip"]

    return {"era": era, "whip": whip}


def get_moneyline_odds(event):
    """
    Pulls DraftKings moneyline odds from the scoreboard's odds block.
    Returns {"home": american_odds_int, "away": american_odds_int} or None if missing.
    """
    try:
        odds_list = event["competitions"][0].get("odds", [])
        if not odds_list:
            return None
        moneyline = odds_list[0]["moneyline"]
        home_odds = int(moneyline["home"]["close"]["odds"])
        away_odds = int(moneyline["away"]["close"]["odds"])
        return {"home": home_odds, "away": away_odds}
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def american_to_implied(odds):
    """Converts American odds to implied win probability (0-1 scale)."""
    if odds < 0:
        return -odds / (-odds + 100)
    else:
        return 100 / (odds + 100)


def get_team_record(competitor: dict) -> str:
    """Pulls W-L record directly from the scoreboard competitor object."""
    records = competitor.get("records", [])
    return records[0].get("summary", "") if records else ""


def get_team_injuries(competitor: dict) -> str:
    """Pulls Out/Doubtful/Day-To-Day players from the scoreboard competitor object."""
    injuries = []
    for player in competitor.get("injuries", []):
        name = player.get("athlete", {}).get("displayName", "")
        status = player.get("status", "")
        if name and status in ["Out", "Doubtful", "Day-To-Day"]:
            injuries.append(f"{name} ({status})")
    return ", ".join(injuries)


def get_team_rest_days(team_id: str):
    """
    Days since this team's last completed game.
    Mirrors the WNBA streak-fetch pattern — one ESPN schedule call per team.
    """
    url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{team_id}/schedule"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
    except Exception:
        return None

    today = (datetime.now(timezone.utc) + timedelta(hours=-5)).date()
    past_dates = []
    for event in data.get("events", []):
        completed = event.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed", False)
        if not completed:
            continue
        utc_str = event.get("date", "")
        try:
            utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            game_day = (utc_dt + timedelta(hours=-5)).date()
        except Exception:
            continue
        if game_day < today:
            past_dates.append(game_day)

    if not past_dates:
        return None
    return (today - max(past_dates)).days