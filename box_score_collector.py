"""
box_score_collector.py
=======================
Pulls full box scores from ESPN for completed games.
Saves to data/box_scores/{sport}/{season_type}/
Covers all sports: NBA, WNBA, NFL, NCAAF, NCAAB, NCAAW

Usage:
  python box_score_collector.py --sport nba --date 2026-06-11
  python box_score_collector.py --sport wnba  # pulls today
  python box_score_collector.py --sport nba --backfill  # pulls all available
"""

import requests
import json
import os
import argparse
from datetime import datetime, timedelta

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
BOX_SCORE_DIR  = os.path.join(BASE_DIR, "data", "box_scores")

ESPN_ENDPOINTS = {
    "nfl":   "http://site.api.espn.com/apis/site/v2/sports/football/nfl",
    "ncaaf": "http://site.api.espn.com/apis/site/v2/sports/football/college-football",
    "nba":   "http://site.api.espn.com/apis/site/v2/sports/basketball/nba",
    "ncaab": "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball",
    "ncaaw": "http://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball",
    "wnba":  "http://site.api.espn.com/apis/site/v2/sports/basketball/wnba",
}

SEASON_TYPE_MAP = {
    1: "preseason",
    2: "regular_season",
    3: "playoff",
    4: "offseason",
}


def ensure_dir(sport: str, season_type: str):
    path = os.path.join(BOX_SCORE_DIR, sport, season_type)
    os.makedirs(path, exist_ok=True)
    return path


def _get(url: str, params: dict = None) -> dict:
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  ESPN error: {e}")
        return {}


def get_player_stats(competitor: dict) -> list:
    """Extract player box score stats from a competitor object."""
    players = []
    statistics = competitor.get("statistics", [])

    # Build stat name lookup
    stat_names = []
    for stat_group in statistics:
        names = stat_group.get("names", [])
        if names:
            stat_names = names
            break

    for athlete_entry in competitor.get("roster", {}).get("entries", []):
        athlete    = athlete_entry.get("athlete", {})
        stats_list = athlete_entry.get("stats", [])

        player_stats = {
            "name":     athlete.get("displayName", ""),
            "position": athlete.get("position", {}).get("abbreviation", ""),
            "jersey":   athlete.get("jersey", ""),
        }

        for i, stat_val in enumerate(stats_list):
            if i < len(stat_names):
                player_stats[stat_names[i]] = stat_val

        players.append(player_stats)

    return players


def fetch_box_score(event_id: str, sport: str) -> dict:
    """Fetch full box score for a specific event from ESPN."""
    base = ESPN_ENDPOINTS.get(sport)
    if not base:
        return {}

    # ESPN summary endpoint has full box score
    data = _get(f"{base}/summary", params={"event": event_id})
    if not data:
        return {}

    # Game info
    header       = data.get("header", {})
    competitions = header.get("competitions", [{}])
    comp         = competitions[0] if competitions else {}
    competitors  = comp.get("competitors", [])

    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})

    home_team  = home.get("team", {}).get("displayName", "")
    away_team  = away.get("team", {}).get("displayName", "")
    home_score = int(home.get("score", 0))
    away_score = int(away.get("score", 0))

    # Season type
    season_type_id = header.get("season", {}).get("type", 2)
    season_type    = SEASON_TYPE_MAP.get(season_type_id, "regular_season")
    season_year    = header.get("season", {}).get("year", datetime.now().year)

    # Team stats
    box_scores = data.get("boxscore", {})
    players_data = box_scores.get("players", [])

    home_players = []
    away_players = []

    for team_data in players_data:
        team_name = team_data.get("team", {}).get("displayName", "")
        stats_groups = team_data.get("statistics", [])

        players_list = []
        for group in stats_groups:
            stat_names = group.get("names", [])
            for athlete in group.get("athletes", []):
                a     = athlete.get("athlete", {})
                stats = athlete.get("stats", [])
                p     = {
                    "name":     a.get("displayName", ""),
                    "position": a.get("position", {}).get("abbreviation", ""),
                    "jersey":   a.get("jersey", ""),
                    "starter":  athlete.get("starter", False),
                    "active":   athlete.get("active", True),
                }
                for i, val in enumerate(stats):
                    if i < len(stat_names):
                        p[stat_names[i]] = val
                players_list.append(p)

        if team_name == home_team:
            home_players = players_list
        elif team_name == away_team:
            away_players = players_list

    # Team totals
    team_stats = box_scores.get("teams", [])
    home_totals = {}
    away_totals = {}

    for team_data in team_stats:
        team_name   = team_data.get("team", {}).get("displayName", "")
        stat_groups = team_data.get("statistics", [])
        totals      = {}
        for stat in stat_groups:
            totals[stat.get("name", "")] = stat.get("displayValue", stat.get("value", ""))
        if team_name == home_team:
            home_totals = totals
        elif team_name == away_team:
            away_totals = totals

    return {
        "event_id":    event_id,
        "sport":       sport,
        "season_year": season_year,
        "season_type": season_type,
        "date":        header.get("competitions", [{}])[0].get("date", "")[:10],
        "game":        f"{away_team} @ {home_team}",
        "final_score": {
            "home": home_score,
            "away": away_score,
            "winner": home_team if home_score > away_score else away_team,
        },
        "home_box": {
            "team":    home_team,
            "totals":  home_totals,
            "players": home_players,
        },
        "away_box": {
            "team":    away_team,
            "totals":  away_totals,
            "players": away_players,
        },
    }


def save_box_score(box: dict):
    """Save a box score to data/box_scores/{sport}/{season_type}/"""
    sport       = box.get("sport", "unknown")
    season_type = box.get("season_type", "regular_season")
    date        = box.get("date", "unknown")
    event_id    = box.get("event_id", "unknown")
    game        = box.get("game", "unknown")

    save_dir  = ensure_dir(sport, season_type)
    safe_game = game.replace(" @ ", "_vs_").replace(" ", "_").replace("/", "-")
    filename  = f"{date}_{safe_game}_{event_id}.json"
    filepath  = os.path.join(save_dir, filename)

    if os.path.exists(filepath):
        print(f"  Already exists: {filename}")
        return

    with open(filepath, "w") as f:
        json.dump(box, f, indent=2)

    print(f"  Saved: {filename} [{season_type}]")


def collect_games_for_date(sport: str, date_str: str):
    """Fetch and save all box scores for a given date."""
    base     = ESPN_ENDPOINTS.get(sport)
    espn_date = date_str.replace("-", "")
    data     = _get(f"{base}/scoreboard", params={"dates": espn_date, "limit": 100})

    if not data:
        print(f"  No data for {sport} on {date_str}")
        return

    events = data.get("events", [])
    print(f"  Found {len(events)} events for {sport} on {date_str}")

    for event in events:
        status    = event.get("competitions", [{}])[0].get("status", {}).get("type", {})
        completed = status.get("completed", False)

        if not completed:
            print(f"  Skipping incomplete: {event.get('name', '')}")
            continue

        event_id = event.get("id", "")
        print(f"  Fetching box score: {event.get('name', '')} ({event_id})")
        box = fetch_box_score(event_id, sport)
        if box:
            save_box_score(box)


def backfill_sport(sport: str, days_back: int = 60):
    """
    Backfill box scores for a sport going back N days.
    Default 60 days covers most of a playoff run.
    """
    print(f"\nBackfilling {sport} — last {days_back} days...")
    today = datetime.now()

    for i in range(days_back):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        print(f"\n  {date_str}")
        collect_games_for_date(sport, date_str)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport",    default="nba", choices=list(ESPN_ENDPOINTS.keys()))
    parser.add_argument("--date",     default=None,  help="YYYY-MM-DD")
    parser.add_argument("--backfill", action="store_true", help="Pull last 60 days")
    parser.add_argument("--days",     type=int, default=60, help="Days to backfill")
    args = parser.parse_args()

    if args.backfill:
        backfill_sport(args.sport, days_back=args.days)
    else:
        date_str = args.date or datetime.now().strftime("%Y-%m-%d")
        print(f"\nCollecting {args.sport} box scores for {date_str}...")
        collect_games_for_date(args.sport, date_str)
        print("\nDone.")
