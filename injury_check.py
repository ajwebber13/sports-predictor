"""
injury_check.py — Culture & Pulse Analytics
Pulls injury reports, team records, and rest days from ESPN free APIs.
Supports NBA and WNBA.
"""

import requests
from datetime import datetime, timezone, timedelta

CENTRAL_OFFSET = -5  # CDT

ESPN_INJURY_ENDPOINTS = {
    "nba":  "basketball/nba",
    "wnba": "basketball/wnba",
}

ESPN_SCOREBOARD_ENDPOINTS = {
    "nba":  "basketball/nba",
    "wnba": "basketball/wnba",
}


# ─────────────────────────────────────────────────────────────
# INJURIES
# ─────────────────────────────────────────────────────────────

def get_injuries(sport: str) -> dict:
    """
    Returns dict of { team_name: [ "Player (Status)", ... ] }
    Only includes Out and Doubtful.
    """
    endpoint = ESPN_INJURY_ENDPOINTS.get(sport)
    if not endpoint:
        return {}

    url = f"http://site.api.espn.com/apis/site/v2/sports/{endpoint}/injuries"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"Injury fetch error ({sport}): {e}")
        return {}

    injuries = {}
    for team_entry in data.get("injuries", []):
        team_name = team_entry.get("team", {}).get("displayName", "")
        players   = []
        for item in team_entry.get("injuries", []):
            status = item.get("status", "")
            if status in ["Out", "Doubtful"]:
                name = item.get("athlete", {}).get("displayName", "Unknown")
                players.append(f"{name} ({status})")
        if players:
            injuries[team_name] = players

    return injuries


# ─────────────────────────────────────────────────────────────
# RECORDS
# ─────────────────────────────────────────────────────────────

def get_records(sport: str) -> dict:
    """
    Returns dict of { team_name: "W-L" }
    """
    endpoint = ESPN_SCOREBOARD_ENDPOINTS.get(sport)
    if not endpoint:
        return {}

    url = f"http://site.api.espn.com/apis/site/v2/sports/{endpoint}/teams"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"Records fetch error ({sport}): {e}")
        return {}

    records = {}
    for team_entry in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        team     = team_entry.get("team", {})
        name     = team.get("displayName", "")
        record   = team.get("record", {}).get("items", [])
        wins     = None
        losses   = None
        for item in record:
            if item.get("type") == "total":
                stats = {s["name"]: s["value"] for s in item.get("stats", [])}
                wins   = int(stats.get("wins", 0))
                losses = int(stats.get("losses", 0))
                break
        if name and wins is not None:
            records[name] = f"{wins}-{losses}"

    return records


# ─────────────────────────────────────────────────────────────
# REST DAYS
# ─────────────────────────────────────────────────────────────

def get_rest_days(sport: str) -> dict:
    """
    Returns dict of { team_name: rest_days (int) }
    Based on days since last completed game in the scoreboard.
    """
    endpoint = ESPN_SCOREBOARD_ENDPOINTS.get(sport)
    if not endpoint:
        return {}

    # Pull last 14 days of scores to find most recent game per team
    today_ct  = datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)
    last_game = {}

    for days_back in range(1, 15):
        date_str = (today_ct - timedelta(days=days_back)).strftime("%Y%m%d")
        url      = f"http://site.api.espn.com/apis/site/v2/sports/{endpoint}/scoreboard?dates={date_str}"
        try:
            r    = requests.get(url, timeout=10)
            data = r.json()
        except:
            continue

        for event in data.get("events", []):
            status = event.get("status", {}).get("type", {}).get("completed", False)
            if not status:
                continue
            for comp in event.get("competitions", []):
                for competitor in comp.get("competitors", []):
                    name = competitor.get("team", {}).get("displayName", "")
                    if name and name not in last_game:
                        last_game[name] = days_back

    return last_game


# ─────────────────────────────────────────────────────────────
# UNIFIED FETCH
# ─────────────────────────────────────────────────────────────

def get_game_context(sport: str) -> dict:
    """
    Returns combined context dict:
    {
        "injuries": { team_name: ["Player (Status)", ...] },
        "records":  { team_name: "W-L" },
        "rest":     { team_name: days_since_last_game }
    }
    """
    print(f"Fetching game context for {sport.upper()}...")
    injuries = get_injuries(sport)
    records  = get_records(sport)
    rest     = get_rest_days(sport)
    print(f"  Injuries: {len(injuries)} teams with reports")
    print(f"  Records:  {len(records)} teams")
    print(f"  Rest:     {len(rest)} teams tracked")
    return {"injuries": injuries, "records": records, "rest": rest}
