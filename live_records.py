"""
live_records.py — Culture & Pulse Analytics
============================================
Pulls live win/loss records for WNBA, NBA, and NCAAB from ESPN.
Replaces the static TEAM_RECORDS dict in nba_wnba_predict.py.

Cached for 6 hours — records don't change mid-day.
Falls back to a safe default (15-15) if ESPN is unreachable.

Usage:
  python live_records.py           # fetch and display all leagues
  python live_records.py wnba      # fetch WNBA only
  python live_records.py refresh   # force cache refresh
"""

import os
import json
import requests
from datetime import datetime, timedelta
from typing import Dict, Tuple

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE    = os.path.join(BASE_DIR, "records_cache.json")
CACHE_TTL_HRS = 6    # records update after games end — 6hrs is safe

DEFAULT_RECORD    = (15, 15)   # mid-season fallback for known teams
LOW_SAMPLE_RECORD = (0, 0)     # forces suppression if team is truly unknown

ESPN_STANDINGS_URLS = {
    "WNBA":  "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/standings",
    "NBA":   "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/standings",
    "NCAAB": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/standings",
}

ESPN_SCOREBOARD_URLS = {
    "WNBA":  "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "NBA":   "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "NCAAB": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.espn.com/",
}


# ─────────────────────────────────────────────
# CACHE
# ─────────────────────────────────────────────

def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(data: dict):
    data["cached_at"] = datetime.now().isoformat()
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"  [Records] Cache write error: {e}")


def _cache_is_fresh(cache: dict) -> bool:
    cached_at = cache.get("cached_at")
    if not cached_at:
        return False
    try:
        age = datetime.now() - datetime.fromisoformat(cached_at)
        return age < timedelta(hours=CACHE_TTL_HRS)
    except Exception:
        return False


# ─────────────────────────────────────────────
# ESPN FETCHERS
# ─────────────────────────────────────────────

def _fetch(url: str) -> dict:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [Records] Fetch error: {e}")
        return {}


def _parse_record_string(record_str: str) -> Tuple[int, int]:
    """
    Parse ESPN record strings like '12-8', '12-8-1' (W-L-OT).
    Returns (wins, losses).
    """
    try:
        parts = str(record_str).strip().split("-")
        wins   = int(parts[0])
        losses = int(parts[1])
        return wins, losses
    except Exception:
        return DEFAULT_RECORD


def fetch_records_from_standings(league: str) -> Dict[str, Tuple[int, int]]:
    """
    Pull records from ESPN standings endpoint.
    Most reliable — full season data for all teams.
    """
    url  = ESPN_STANDINGS_URLS.get(league)
    data = _fetch(url)
    if not data:
        return {}

    records = {}

    # ESPN standings structure: data.children[].standings.entries[]
    children = data.get("children", [])
    if not children:
        # Some leagues return entries directly
        children = [data]

    for division in children:
        standings = division.get("standings", {})
        entries   = standings.get("entries", [])

        for entry in entries:
            team_info = entry.get("team", {})
            team_name = team_info.get("displayName", "")
            if not team_name:
                continue

            wins = losses = None
            for stat in entry.get("stats", []):
                name = stat.get("name", "").lower()
                val  = stat.get("value", 0)
                if name == "wins":
                    wins = int(val)
                elif name == "losses":
                    losses = int(val)
                elif name == "overall" and wins is None:
                    # Sometimes stored as "12-8" string
                    display = stat.get("displayValue", "")
                    if "-" in display:
                        wins, losses = _parse_record_string(display)

            if wins is not None and losses is not None:
                records[team_name] = (wins, losses)

    return records


def fetch_records_from_scoreboard(league: str) -> Dict[str, Tuple[int, int]]:
    """
    Pull records from ESPN scoreboard competitor data.
    Fallback if standings endpoint fails — only returns teams playing today.
    """
    url  = ESPN_SCOREBOARD_URLS.get(league)
    data = _fetch(url)
    if not data:
        return {}

    records = {}

    for event in data.get("events", []):
        comp        = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])

        for c in competitors:
            team_name = c.get("team", {}).get("displayName", "")
            if not team_name:
                continue

            # Record stored in competitor.records[]
            for rec in c.get("records", []):
                rec_type = rec.get("type", "")
                summary  = rec.get("summary", "")   # e.g. "12-8"
                if rec_type in ("total", "overall") and "-" in summary:
                    records[team_name] = _parse_record_string(summary)
                    break

    return records


# ─────────────────────────────────────────────
# WNBA — use wnba_data.py for richer data
# ─────────────────────────────────────────────

def fetch_wnba_records_native() -> Dict[str, Tuple[int, int]]:
    """
    Use the existing wnba_data.get_team_stats() flow.
    Most accurate for WNBA — pulls from team endpoint directly.
    """
    try:
        from wnba_data import get_team_stats, TEAM_IDS
        records = {}
        for team_name in TEAM_IDS:
            stats = get_team_stats(team_name)
            if stats:
                records[team_name] = (stats.wins, stats.losses)
        return records
    except Exception as e:
        print(f"  [Records] wnba_data error: {e}")
        return {}


# ─────────────────────────────────────────────
# MAIN PUBLIC FUNCTION
# ─────────────────────────────────────────────

def get_live_records(league: str, force_refresh: bool = False) -> Dict[str, Tuple[int, int]]:
    """
    Returns live win/loss records for all teams in a league.

    Dict format: {"Team Name": (wins, losses), ...}

    Priority:
      WNBA  → wnba_data native → ESPN standings → ESPN scoreboard
      NBA   → ESPN standings   → ESPN scoreboard
      NCAAB → ESPN standings   → ESPN scoreboard

    Falls back to DEFAULT_RECORD (15-15) per team if all sources fail.
    """
    cache     = _load_cache()
    cache_key = f"{league.upper()}_records"

    if not force_refresh and _cache_is_fresh(cache) and cache_key in cache:
        # Convert lists back to tuples (JSON serializes tuples as lists)
        return {k: tuple(v) for k, v in cache[cache_key].items()}

    print(f"  [Records] Fetching live {league} records...")
    records = {}

    if league.upper() == "WNBA":
        records = fetch_wnba_records_native()
        if not records:
            records = fetch_records_from_standings("WNBA")
        if not records:
            records = fetch_records_from_scoreboard("WNBA")

    elif league.upper() == "NBA":
        records = fetch_records_from_standings("NBA")
        if not records:
            records = fetch_records_from_scoreboard("NBA")

    elif league.upper() == "NCAAB":
        records = fetch_records_from_standings("NCAAB")
        if not records:
            records = fetch_records_from_scoreboard("NCAAB")

    if records:
        print(f"  [Records] {len(records)} {league} teams loaded.")
        cache[cache_key] = records
        _save_cache(cache)
    else:
        print(f"  [Records] All sources failed — confidence filter will use default record.")

    return records


def get_record(team_name: str, league: str, records: Dict[str, Tuple[int, int]] = None) -> Tuple[int, int]:
    """
    Get win/loss record for a single team.

    Pass in a pre-fetched records dict to avoid redundant API calls.
    Falls back to live fetch if not provided.
    """
    if records is None:
        records = get_live_records(league)

    return records.get(team_name, DEFAULT_RECORD)


# ─────────────────────────────────────────────
# STANDALONE DISPLAY
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    force   = "refresh" in sys.argv
    leagues = ["WNBA", "NBA", "NCAAB"]

    # Allow single league arg: python live_records.py wnba
    for arg in sys.argv[1:]:
        if arg.upper() in leagues:
            leagues = [arg.upper()]
            break

    for league in leagues:
        print(f"\n{'='*52}")
        print(f"  {league} RECORDS — {'FORCE REFRESH' if force else 'Cached or Live'}")
        print(f"{'='*52}")

        records = get_live_records(league, force_refresh=force)
        if not records:
            print(f"  No records available for {league}")
            continue

        sorted_r = sorted(records.items(), key=lambda x: x[1][0], reverse=True)
        for team, (w, l) in sorted_r:
            total = w + l
            pct   = round(w / total, 3) if total > 0 else 0.0
            flag  = "  ⚠ LOW SAMPLE" if total < 10 else ""
            print(f"  {team:<35} {w}-{l}  ({pct:.3f}){flag}")
