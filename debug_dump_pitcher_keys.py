"""
debug_dump_pitcher_keys.py

One-off diagnostic — pulls ONE real completed MLB game's box score and
prints the raw "statistics" blocks (both batting and pitching) so we
can see ESPN's ACTUAL key names instead of guessing. The batting
parser's keys (atBats, hits, runs, RBIs, homeRuns, walks) are already
confirmed correct since batting props have been working — this is
purely to find the real pitching equivalents of the guessed
inningsPitched/strikeouts/earnedRuns/walks/hits keys that turned out
to return 0 rows.

Usage:
    python debug_dump_pitcher_keys.py 20260719

Pass any recent date (YYYYMMDD) that had real MLB games — same format
mlb_player_stats.py's update/backfill functions already use.
"""

import sys
import json
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"


def get_one_game_id(date_str: str):
    resp = requests.get(ESPN_SCOREBOARD_URL, params={"dates": date_str}, headers=HEADERS, timeout=10)
    data = resp.json()
    events = data.get("events", [])
    for e in events:
        status = e.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed", False)
        if status:
            return e["id"], e.get("shortName", "")
    return None, None


def dump_box_score(event_id: str):
    url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={event_id}"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    data = resp.json()

    boxscore = data.get("boxscore", {})
    players = boxscore.get("players", [])

    if not players:
        print("No 'players' block found in boxscore — dumping top-level boxscore keys instead:")
        print(list(boxscore.keys()))
        return

    for team_data in players:
        team_name = team_data.get("team", {}).get("displayName", "UNKNOWN")
        print(f"\n{'='*60}\nTEAM: {team_name}\n{'='*60}")
        stats_list = team_data.get("statistics", [])
        for block in stats_list:
            block_name = block.get("name", "unnamed")
            keys = block.get("keys", [])
            print(f"\n--- STAT BLOCK: '{block_name}' ---")
            print(f"keys: {keys}")
            athletes = block.get("athletes", [])
            if athletes:
                first = athletes[0]
                name = first.get("athlete", {}).get("displayName", "?")
                stats = first.get("stats", [])
                print(f"first athlete: {name}")
                print(f"raw stats array: {stats}")
                if len(keys) == len(stats):
                    print("keys -> values:")
                    for k, v in zip(keys, stats):
                        print(f"  {k}: {v}")


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else "20260719"
    print(f"Looking for a completed game on {date_str}...")
    event_id, short_name = get_one_game_id(date_str)
    if not event_id:
        print(f"No completed game found for {date_str} — try a different date.")
        sys.exit(1)
    print(f"Found: {short_name} (event {event_id})\n")
    dump_box_score(event_id)
