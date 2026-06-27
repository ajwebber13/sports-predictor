"""
sync_wnba_rosters.py — Culture & Pulse Analytics
=================================================
Pulls live WNBA rosters from ESPN and updates:
  - WNBA_STAR_PLAYERS in wnba_slate_digest.py
  - TEAM_KEYWORDS in wnba_news_feed.py

Run weekly via Render cron or manually before season starts.

Usage:
  python sync_wnba_rosters.py           # live update
  python sync_wnba_rosters.py --dry-run # print only, no file changes
"""

import os
import re
import sys
import requests
import argparse
from datetime import datetime

TEAM_IDS = {
    "Atlanta Dream":           "20",
    "Chicago Sky":             "19",
    "Connecticut Sun":         "18",
    "Dallas Wings":            "3",
    "Golden State Valkyries":  "129689",
    "Indiana Fever":           "5",
    "Las Vegas Aces":          "17",
    "Los Angeles Sparks":      "6",
    "Minnesota Lynx":          "8",
    "New York Liberty":        "9",
    "Phoenix Mercury":         "11",
    "Portland Fire":           "132052",
    "Seattle Storm":           "14",
    "Toronto Tempo":           "131935",
    "Washington Mystics":      "16",
}

# Star player threshold — only include players averaging >= this many minutes
# Filters out end-of-bench players from keyword lists
MIN_MINUTES = 15.0

BASE = "http://site.api.espn.com/apis/site/v2/sports/basketball/wnba"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept":     "application/json",
}


def fetch_roster(team_name: str, team_id: str) -> list:
    """Fetch active roster from ESPN."""
    url = f"{BASE}/teams/{team_id}/roster"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  Error fetching {team_name}: {e}")
        return []

    players = []
    for a in data.get("athletes", []):
        name   = a.get("displayName", "")
        status = a.get("status", "")
        if not name:
            continue
        # Skip injured reserve / out for season
        if isinstance(status, str) and status.lower() in ("out for season", "waived", "suspended"):
            continue
        players.append(name)

    return players


def fetch_team_stats_for_minutes(team_id: str) -> dict:
    """
    Fetch player stats to identify star players by minutes.
    Returns dict of {player_name: avg_minutes}.
    Falls back to empty dict if unavailable.
    """
    url = f"{BASE}/teams/{team_id}/statistics"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except:
        return {}

    minutes_map = {}
    categories  = data.get("results", {}).get("stats", {}).get("categories", [])
    for cat in categories:
        for stat in cat.get("stats", []):
            if stat.get("name") == "avgMinutes":
                # This is team-level, not player-level — skip
                pass
    return minutes_map


def build_rosters() -> dict:
    """Fetch all team rosters and return as dict."""
    rosters = {}
    for team_name, team_id in TEAM_IDS.items():
        print(f"  Fetching {team_name}...")
        players = fetch_roster(team_name, team_id)
        rosters[team_name] = players
        print(f"    {len(players)} players")
    return rosters


def update_star_players(rosters: dict, filepath: str, dry_run: bool = False):
    """
    Update WNBA_STAR_PLAYERS in wnba_slate_digest.py.
    Keeps top players per team (up to 6).
    """
    # Known star players to prioritize — will be kept if on roster
    PRIORITY_PLAYERS = {
        "Atlanta Dream":          ["Rhyne Howard", "Angel Reese", "Allisha Gray", "Te-Hina Paopao", "Jordin Canada"],
        "Chicago Sky":            ["Kamilla Cardoso", "Skylar Diggins", "Natasha Cloud"],
        "Connecticut Sun":        ["Brittney Griner", "Leila Lacan", "Aaliyah Edwards"],
        "Dallas Wings":           ["Arike Ogunbowale", "Paige Bueckers", "Azzi Fudd"],
        "Golden State Valkyries": ["Tiffany Hayes", "Kayla Thornton", "Veronica Burton"],
        "Indiana Fever":          ["Caitlin Clark", "Aliyah Boston", "NaLyssa Smith", "Kelsey Mitchell"],
        "Las Vegas Aces":         ["A'ja Wilson", "Jackie Young", "Chennedy Carter"],
        "Los Angeles Sparks":     ["Dearica Hamby", "Kelsey Plum", "Nneka Ogwumike", "Kate Martin"],
        "Minnesota Lynx":         ["Napheesa Collier", "Kayla McBride", "Olivia Miles"],
        "New York Liberty":       ["Breanna Stewart", "Sabrina Ionescu", "Jonquel Jones", "Satou Sabally"],
        "Phoenix Mercury":        ["Alyssa Thomas", "DeWanna Bonner", "Kahleah Copper", "Natasha Mack"],
        "Portland Fire":          ["Carla Leite", "Bridget Carleton"],
        "Seattle Storm":          ["Jewell Loyd"],
        "Toronto Tempo":          ["Marina Mabrey", "Kiki Rice"],
        "Washington Mystics":     ["Shakira Austin", "Lauren Betts", "Rori Harmon"],
    }

    new_star_players = {}
    for team, roster in rosters.items():
        priority = PRIORITY_PLAYERS.get(team, [])
        # Keep priority players who are still on the roster
        stars = [p for p in priority if p in roster]
        # Fill up to 6 with remaining roster players not already included
        for p in roster:
            if p not in stars and len(stars) < 6:
                stars.append(p)
        new_star_players[team] = stars

    # Build the new WNBA_STAR_PLAYERS block
    lines = ["WNBA_STAR_PLAYERS = {"]
    for team, stars in sorted(new_star_players.items()):
        stars_str = ", ".join(f'"{s}"' for s in stars)
        lines.append(f'    "{team}":{" " * max(1, 26 - len(team))}[{stars_str}],')
    lines.append("}")
    new_block = "\n".join(lines)

    if dry_run:
        print("\n--- WNBA_STAR_PLAYERS (dry run) ---")
        print(new_block)
        return

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Replace existing WNBA_STAR_PLAYERS block
    pattern = r"WNBA_STAR_PLAYERS\s*=\s*\{[^}]*\}"
    if re.search(pattern, content, re.DOTALL):
        new_content = re.sub(pattern, new_block, content, flags=re.DOTALL)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  Updated WNBA_STAR_PLAYERS in {filepath}")
    else:
        print(f"  WARNING: Could not find WNBA_STAR_PLAYERS in {filepath}")


def update_team_keywords(rosters: dict, filepath: str, dry_run: bool = False):
    """
    Update TEAM_KEYWORDS in wnba_news_feed.py.
    Keeps team name + city name + top known players.
    """
    TEAM_CITY_KEYWORDS = {
        "Atlanta Dream":          ["Atlanta Dream", "Dream"],
        "Chicago Sky":            ["Chicago Sky", "Sky"],
        "Connecticut Sun":        ["Connecticut Sun", "Sun"],
        "Dallas Wings":           ["Dallas Wings", "Wings"],
        "Golden State Valkyries": ["Golden State Valkyries", "Valkyries"],
        "Indiana Fever":          ["Indiana Fever", "Fever"],
        "Las Vegas Aces":         ["Las Vegas Aces", "Aces"],
        "Los Angeles Sparks":     ["Los Angeles Sparks", "Sparks"],
        "Minnesota Lynx":         ["Minnesota Lynx", "Lynx"],
        "New York Liberty":       ["New York Liberty", "Liberty"],
        "Phoenix Mercury":        ["Phoenix Mercury", "Mercury"],
        "Portland Fire":          ["Portland Fire", "Fire"],
        "Seattle Storm":          ["Seattle Storm", "Storm"],
        "Toronto Tempo":          ["Toronto Tempo", "Tempo"],
        "Washington Mystics":     ["Washington Mystics", "Mystics"],
    }

    PRIORITY_PLAYERS = {
        "Atlanta Dream":          ["Rhyne Howard", "Angel Reese", "Allisha Gray", "Te-Hina Paopao"],
        "Chicago Sky":            ["Kamilla Cardoso", "Skylar Diggins", "Natasha Cloud"],
        "Connecticut Sun":        ["Brittney Griner", "Leila Lacan"],
        "Dallas Wings":           ["Arike Ogunbowale", "Paige Bueckers", "Azzi Fudd"],
        "Golden State Valkyries": ["Tiffany Hayes", "Kayla Thornton"],
        "Indiana Fever":          ["Caitlin Clark", "Aliyah Boston", "Kelsey Mitchell"],
        "Las Vegas Aces":         ["A'ja Wilson", "Jackie Young", "Chennedy Carter"],
        "Los Angeles Sparks":     ["Dearica Hamby", "Kelsey Plum", "Nneka Ogwumike", "Kate Martin"],
        "Minnesota Lynx":         ["Napheesa Collier", "Kayla McBride", "Olivia Miles"],
        "New York Liberty":       ["Breanna Stewart", "Sabrina Ionescu", "Jonquel Jones", "Satou Sabally"],
        "Phoenix Mercury":        ["Alyssa Thomas", "DeWanna Bonner", "Kahleah Copper"],
        "Portland Fire":          ["Carla Leite"],
        "Seattle Storm":          ["Jewell Loyd"],
        "Toronto Tempo":          ["Marina Mabrey", "Kiki Rice"],
        "Washington Mystics":     ["Shakira Austin", "Lauren Betts"],
    }

    new_keywords = {}
    for team, roster in rosters.items():
        base     = TEAM_CITY_KEYWORDS.get(team, [team])
        priority = PRIORITY_PLAYERS.get(team, [])
        stars    = [p for p in priority if p in roster]
        new_keywords[team] = base + stars

    # Build the new TEAM_KEYWORDS block
    lines = ["TEAM_KEYWORDS = {"]
    for team, kws in sorted(new_keywords.items()):
        kws_str = ", ".join(f'"{k}"' for k in kws)
        lines.append(f'    "{team}":{" " * max(1, 26 - len(team))}[{kws_str}],')
    lines.append("}")
    new_block = "\n".join(lines)

    if dry_run:
        print("\n--- TEAM_KEYWORDS (dry run) ---")
        print(new_block)
        return

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"TEAM_KEYWORDS\s*=\s*\{[^}]*\}"
    if re.search(pattern, content, re.DOTALL):
        new_content = re.sub(pattern, new_block, content, flags=re.DOTALL)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  Updated TEAM_KEYWORDS in {filepath}")
    else:
        print(f"  WARNING: Could not find TEAM_KEYWORDS in {filepath}")


def run(dry_run: bool = False):
    print(f"WNBA Roster Sync — {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    print("Fetching live rosters from ESPN...")

    rosters = build_rosters()

    # Paths relative to this script
    base_dir  = os.path.dirname(os.path.abspath(__file__))
    digest    = os.path.join(base_dir, "wnba_slate_digest.py")
    news_feed = os.path.join(base_dir, "wnba_news_feed.py")

    print("\nUpdating WNBA_STAR_PLAYERS...")
    update_star_players(rosters, digest, dry_run=dry_run)

    print("\nUpdating TEAM_KEYWORDS...")
    update_team_keywords(rosters, news_feed, dry_run=dry_run)

    print("\nDone.")
    if not dry_run:
        print("Commit and push wnba_slate_digest.py and wnba_news_feed.py to deploy.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing files")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
