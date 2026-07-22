"""
mlb_matchup.py - Culture & Pulse Analytics
Team-level batter-vs-pitcher matchup stats via the MLB Stats API
(statsapi.mlb.com) — NOT ESPN, which doesn't expose this data.

v2 (2026-07-22): rebuilt after live debug confirmed there is NO
team-level vsPlayer endpoint — /teams/{id}/stats?stats=vsPlayer
returns an empty stats list every time (confirmed live, not a wrong
key — the endpoint itself doesn't support this at the team level).
MLB Stats API only supports vsPlayer at the PERSON level. This
version pulls the team's active batting roster, then calls
vsPlayer once per batter (in parallel, bounded), and aggregates.

REAL TRADEOFF: this means significantly more API calls per game
(roster fetch + up to ~13 per-batter calls) than the original v1
design. Concurrency is deliberately kept LOWER than routes_mlb.py's
game-level thread pool (6 workers) because this pool runs NESTED
inside each of those 6 game threads — 6 games x this pool's workers
could otherwise stack into 30+ simultaneous connections to
statsapi.mlb.com and risk 429s. Kept at 3 workers here as a
conservative starting point; raise only if logs show no rate-limit
errors after a real multi-day run.

TEAM-LEVEL, not player-level: pregame we only know the probable
pitcher, not the confirmed starting 9 batters (lineups post ~2-3hrs
before first pitch). This aggregates the active roster's history
against that pitcher instead of guessing at specific batters.

Every function here degrades to a neutral/None/zero result on any
failure — never fabricates a number, same principle as
get_run_line_odds()/get_total_odds().
"""

import requests
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed

STATSAPI_BASE = "https://statsapi.mlb.com/api/v1"

MATCHUP_MAX_WORKERS = 3  # see module docstring — kept low, this pool nests inside routes_mlb.py's game-level pool

# MLB Stats API team IDs — DIFFERENT from ESPN's MLB_TEAM_IDS in
# mlb_data.py. Do not mix the two ID systems.
MLB_STATSAPI_TEAM_IDS = {
    "Los Angeles Angels": 108,
    "Arizona Diamondbacks": 109,
    "Baltimore Orioles": 110,
    "Boston Red Sox": 111,
    "Chicago Cubs": 112,
    "Cincinnati Reds": 113,
    "Cleveland Guardians": 114,
    "Colorado Rockies": 115,
    "Detroit Tigers": 116,
    "Houston Astros": 117,
    "Kansas City Royals": 118,
    "Los Angeles Dodgers": 119,
    "Washington Nationals": 120,
    "New York Mets": 121,
    "Athletics": 133,
    "Pittsburgh Pirates": 134,
    "San Diego Padres": 135,
    "Seattle Mariners": 136,
    "San Francisco Giants": 137,
    "St. Louis Cardinals": 138,
    "Tampa Bay Rays": 139,
    "Texas Rangers": 140,
    "Toronto Blue Jays": 141,
    "Minnesota Twins": 142,
    "Philadelphia Phillies": 143,
    "Atlanta Braves": 144,
    "Chicago White Sox": 145,
    "Miami Marlins": 146,
    "New York Yankees": 147,
    "Milwaukee Brewers": 158,
}


@lru_cache(maxsize=64)
def get_pitcher_statsapi_id(pitcher_name: str) -> int | None:
    """
    Looks up a pitcher's MLB Stats API person ID by name.
    Cached per name for the life of the process.
    """
    if not pitcher_name:
        return None

    try:
        resp = requests.get(f"{STATSAPI_BASE}/people/search",
                             params={"names": pitcher_name}, timeout=10)
        data = resp.json()
        people = data.get("people", [])
        if not people:
            return None
        return people[0].get("id")
    except Exception as e:
        print(f"  Matchup: pitcher ID lookup failed ({pitcher_name}): {e}")
        return None


@lru_cache(maxsize=32)
def get_active_batters(team_name: str) -> tuple:
    """
    Pulls the team's active roster and returns (id, name) tuples for
    non-pitchers only. Cached per team for the life of the process —
    roster doesn't meaningfully change within a single run.
    Returns empty tuple on any failure or unknown team.
    """
    team_id = MLB_STATSAPI_TEAM_IDS.get(team_name)
    if team_id is None:
        return ()

    try:
        resp = requests.get(f"{STATSAPI_BASE}/teams/{team_id}/roster",
                             params={"rosterType": "active"}, timeout=10)
        data = resp.json()
        roster = data.get("roster", [])
        batters = []
        for entry in roster:
            position = entry.get("position", {}).get("abbreviation", "")
            if position == "P":
                continue
            person = entry.get("person", {})
            if person.get("id") and person.get("fullName"):
                batters.append((person["id"], person["fullName"]))
        return tuple(batters)
    except Exception as e:
        print(f"  Matchup: roster fetch failed ({team_name}): {e}")
        return ()


def _get_batter_vs_pitcher(batter_id: int, pitcher_id: int) -> dict:
    """One batter's career line against one pitcher. {"ops": float|None, "at_bats": int}."""
    try:
        resp = requests.get(f"{STATSAPI_BASE}/people/{batter_id}/stats",
                             params={"stats": "vsPlayer", "opposingPlayerId": pitcher_id, "group": "hitting"},
                             timeout=10)
        data = resp.json()
        stats_list = data.get("stats", [])
        if not stats_list:
            return {"ops": None, "at_bats": 0}
        splits = stats_list[0].get("splits", [])
        if not splits:
            return {"ops": None, "at_bats": 0}
        stat = splits[0].get("stat", {})
        at_bats = int(stat.get("atBats", 0))
        ops = float(stat.get("ops", 0)) if stat.get("ops") else None
        return {"ops": ops, "at_bats": at_bats}
    except Exception:
        return {"ops": None, "at_bats": 0}


def get_team_vs_pitcher(team_name: str, pitcher_name: str) -> dict:
    """
    Returns the team's ACTIVE ROSTER aggregate batting line against
    this pitcher: {"ops": float|None, "at_bats": int}. Weighted by
    at-bats across all batters with any history against this pitcher.
    Returns {"ops": None, "at_bats": 0} if unavailable (new pitcher,
    no roster match, or any lookup/API failure).
    """
    empty = {"ops": None, "at_bats": 0}

    pitcher_id = get_pitcher_statsapi_id(pitcher_name)
    if pitcher_id is None:
        return empty

    batters = get_active_batters(team_name)
    if not batters:
        return empty

    total_ab = 0
    weighted_ops_sum = 0.0

    with ThreadPoolExecutor(max_workers=MATCHUP_MAX_WORKERS) as executor:
        futures = {
            executor.submit(_get_batter_vs_pitcher, batter_id, pitcher_id): batter_id
            for batter_id, _ in batters
        }
        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception:
                continue
            if result["ops"] is not None and result["at_bats"] > 0:
                total_ab += result["at_bats"]
                weighted_ops_sum += result["ops"] * result["at_bats"]

    if total_ab == 0:
        return empty

    return {"ops": round(weighted_ops_sum / total_ab, 3), "at_bats": total_ab}


LEAGUE_AVG_OPS = 0.715  # rough MLB league-average OPS baseline, used as the neutral comparison point


def get_matchup_adj(matchup: dict) -> float:
    """
    Converts a team-vs-pitcher OPS split into a small run adjustment.
    Damped hard on purpose — aggregated across many batters' small
    individual samples, so this nudges rather than drives the
    projection. Returns 0.0 if fewer than 15 combined at-bats
    (not enough signal).
    """
    if matchup["at_bats"] < 15 or matchup["ops"] is None:
        return 0.0

    ops_diff = matchup["ops"] - LEAGUE_AVG_OPS
    return round(ops_diff * 2.0 * 0.15, 3)
