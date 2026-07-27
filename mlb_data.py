"""
mlb_data.py
Live MLB data pipeline — mirrors cfb_data.py / nfl_data.py pattern.
"""

import requests
from functools import lru_cache
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
    

@lru_cache(maxsize=64)
def get_team_stats(team_name, season=None):
    """
    Fetch team stats, gated on whether stat categories exist —
    NOT on win/loss record (ESPN's record endpoint is unreliable,
    confirmed during the CFB build).

    Cached per (team_name, season) for the life of the process — a
    team's season stats don't meaningfully change within a single
    render_job.py run, and doubleheaders (or /mlb/predictions and
    /mlb/edges both running the same day) would otherwise refetch the
    exact same team 2-4x for no reason. This is the main real
    contributor to the per-game external-call count that was timing
    out mlb_edges() at 60s — see render_job.py's timeout comment for
    the fuller picture (the other calls, get_starting_pitcher()/
    get_pitcher_stats(), turned out to be pure data-parsing with no
    network call at all, not part of the bottleneck)."""
    team_id = MLB_TEAM_IDS.get(team_name)
    if team_id is None:
        return _flat_defaults()

    params = {"season": season} if season else {}
    resp = requests.get(ESPN_TEAM_STATS_URL.format(team_id=team_id), params=params)

    if resp.status_code != 200:
        return _flat_defaults()

    data = resp.json()

    # FIXED 2026-07-26: ESPN restructured this endpoint at some point —
    # confirmed live via debug_team_stats.py that the top-level "splits"
    # key Drew's code was reading no longer contains season-total stats.
    # It still exists, but now holds per-OPPONENT breakdowns (71 entries,
    # one per team faced this season) — same key name, different meaning,
    # classic silent schema-drift trap. The real season aggregate now
    # lives at results.stats.categories (the "All Splits"/"Total" split).
    # Every call was silently hitting the `if not categories: return
    # _flat_defaults()` branch below and falling back to the flat 4.5
    # runs/game default for every team, every game — confirmed via
    # check_base_runs.py showing zero variance across 133 real MLB
    # predictions. Wrapped in a list since _parse_stat_categories()
    # expects to iterate over a list of splits (unchanged otherwise —
    # there's only one real split now instead of several, so its
    # best-split-by-atbats selection logic just picks the only one).
    results_stats = data.get("results", {}).get("stats")
    categories = [results_stats] if results_stats else []

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


def get_run_line_odds(event):
    """
    Pulls the MLB run line (baseball's spread — standard is +/-1.5,
    occasionally +/-2.5 in lopsided games) from the same ESPN odds
    block get_moneyline_odds() already reads successfully.

    ESPN's odds object follows the same {home:{close:{...}},
    away:{close:{...}}} shape for every market (confirmed working for
    "moneyline" above) — "pointSpread" is the documented key for this
    market. line/odds are read the same way "moneyline" is.

    Returns {"home_line": float, "home_odds": int, "away_line": float,
    "away_odds": int} or None if missing/unavailable. NOT YET VERIFIED
    against a live payload (2026 MLB in-season data needed to confirm
    ESPN actually populates "pointSpread" the same way "moneyline" is
    populated for every game) — same caveat NFL's game log parsing
    carried until a real debug_dump_keys() check confirmed field names.
    If this key doesn't match ESPN's real payload, this returns None
    (never fabricates a line) and mlb_predictor.py degrades to
    moneyline-only for that game, same as today.

    GUARD added 2026-07-24: a real MLB run line is NEVER exactly 0 —
    it's always a half-integer (+/-1.5, occasionally +/-2.5). Same bug
    class as the confirmed WNBA/NFL/CFB total_line=0 garbage-data
    incident (see calibration-and-mlb-gap notes): a placeholder/error
    entry from the odds feed returning 0 would otherwise be trusted as
    a real line. Treated as missing data (None), same as a genuinely
    absent key, rather than fed into the predictor.
    """
    try:
        odds_list = event["competitions"][0].get("odds", [])
        if not odds_list:
            return None
        spread = odds_list[0]["pointSpread"]
        home_line = float(spread["home"]["close"]["line"])
        away_line = float(spread["away"]["close"]["line"])
        if home_line == 0 or away_line == 0:
            return None
        home_odds = int(spread["home"]["close"]["odds"])
        away_odds = int(spread["away"]["close"]["odds"])
        return {"home_line": home_line, "home_odds": home_odds, "away_line": away_line, "away_odds": away_odds}
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def get_total_odds(event):
    """
    Pulls the MLB over/under total from the same ESPN odds block.
    "total" is the documented key, mirroring "moneyline"/"pointSpread".

    Returns {"line": float, "over_odds": int, "under_odds": int} or
    None if missing.

    FIXED (2026-07-20): confirmed live against a real in-season game —
    the "total" key IS correct (it was never a wrong-key problem the
    way the docstring worried it might be), but ESPN's line field
    comes back as a STRING with an o/u prefix baked in — "o7.5" for
    the over line, "u7.5" for the under line — not a plain number.
    float("o7.5") raises ValueError, which the bare except below was
    silently swallowing and turning into None every single time,
    regardless of whether the game had real total odds. Stripping the
    leading o/u character before the float() call fixes it. Odds
    themselves ("-110") were always plain numeric strings and never
    had this problem — only the line field does.

    GUARD added 2026-07-24: a real MLB total is never 0 or negative —
    real games run roughly 6-11. Same bug class as the confirmed
    WNBA/NFL/CFB total_line=0 garbage-data incident, where a
    placeholder/error entry from the odds feed fed the Monte Carlo sim
    an impossible line and produced a model_prob near 100%. Treated as
    missing data (None) here before it can reach the predictor.
    """
    try:
        odds_list = event["competitions"][0].get("odds", [])
        if not odds_list:
            return None
        total = odds_list[0]["total"]
        raw_line = str(total["over"]["close"]["line"])
        line = float(raw_line.lstrip("ouOU"))
        if line <= 0:
            return None
        over_odds = int(total["over"]["close"]["odds"])
        under_odds = int(total["under"]["close"]["odds"])
        return {"line": line, "over_odds": over_odds, "under_odds": under_odds}
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