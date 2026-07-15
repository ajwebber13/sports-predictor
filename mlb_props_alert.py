"""
mlb_props_alert.py — Culture & Pulse Analytics
================================================
Sends a standalone Telegram alert with today's MLB player props,
grouped BY GAME. Mirrors wnba_props_alert.py, scoped to the 4
batting stats mlb_player_stats.py actually captures: Hits, RBIs,
Runs, Home Runs. No situational splits (opponent/home-away) yet —
mlb_game_log doesn't track those per at-bat.

Run order (same pattern as WNBA):
  1. fetch_prizepicks_props.py --sport mlb runs first, writes to player_props
  2. mlb_props_alert.py runs after, reads what step 1 wrote

Usage:
    py mlb_props_alert.py            # send today's alert
    py mlb_props_alert.py --dry-run  # print instead of sending
"""

import os
import sys
import argparse
import time
import requests
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from prop_hit_rates import setup_props_table

CENTRAL_OFFSET = -5

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"

STRONG_THRESHOLD = 80  # hit_rate_overall >= this -> shown as a strong 'over' play
FADE_THRESHOLD = 20    # hit_rate_overall <= this -> under_rate >= 80 -> fade candidate
MIN_GAMES = 5
MIN_GAMES_COLUMN = "games_overall"

STAT_LABELS = {
    "hits": "HITS",
    "rbis": "RBI",
    "runs": "RUNS",
    "hr":   "HR",
}

TEAM_ABBR = {
    "Arizona Diamondbacks": "ARI", "Athletics": "ATH", "Atlanta Braves": "ATL",
    "Baltimore Orioles": "BAL", "Boston Red Sox": "BOS", "Chicago Cubs": "CHC",
    "Chicago White Sox": "CWS", "Cincinnati Reds": "CIN", "Cleveland Guardians": "CLE",
    "Colorado Rockies": "COL", "Detroit Tigers": "DET", "Houston Astros": "HOU",
    "Kansas City Royals": "KC", "Los Angeles Angels": "LAA", "Los Angeles Dodgers": "LAD",
    "Miami Marlins": "MIA", "Milwaukee Brewers": "MIL", "Minnesota Twins": "MIN",
    "New York Mets": "NYM", "New York Yankees": "NYY", "Philadelphia Phillies": "PHI",
    "Pittsburgh Pirates": "PIT", "San Diego Padres": "SD", "San Francisco Giants": "SF",
    "Seattle Mariners": "SEA", "St. Louis Cardinals": "STL", "Tampa Bay Rays": "TB",
    "Texas Rangers": "TEX", "Toronto Blue Jays": "TOR", "Washington Nationals": "WSH",
}

DIVIDER = "\u2501" * 20


def abbr(team: str) -> str:
    return TEAM_ABBR.get(team, team.split()[-1] if team else "")


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def get_player_team(player_name: str) -> str:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT team_name FROM mlb_game_log
        WHERE player_name = ?
        ORDER BY date DESC
        LIMIT 1
    """, (player_name,))
    row = c.fetchone()
    conn.close()
    return row["team_name"] if row else ""


def fetch_today_props(date_str: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT player_name, stat, line, hit_rate_overall, confidence_tier,
               game_home_team, game_away_team
        FROM player_props
        WHERE date = ? AND sport = 'mlb'
          AND confidence_tier = 'green'
          AND hit_rate_overall IS NOT NULL
          AND hit_rate_overall >= ?
          AND {MIN_GAMES_COLUMN} >= ?
        ORDER BY hit_rate_overall DESC
    """, (date_str, STRONG_THRESHOLD, MIN_GAMES))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def fetch_fade_props(date_str: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT player_name, stat, line, hit_rate_overall,
               game_home_team, game_away_team
        FROM player_props
        WHERE date = ? AND sport = 'mlb'
          AND hit_rate_overall IS NOT NULL
          AND hit_rate_overall <= ?
          AND confidence_tier != 'insufficient'
          AND {MIN_GAMES_COLUMN} >= ?
        ORDER BY hit_rate_overall ASC
    """, (date_str, FADE_THRESHOLD, MIN_GAMES))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def format_line(prop: dict, team: str, emoji: str) -> str:
    stat_label = STAT_LABELS.get(prop["stat"], prop["stat"].upper())
    pct        = prop["hit_rate_overall"]
    pct_str    = f"{pct:.1f}".rstrip("0").rstrip(".") if pct % 1 else f"{int(pct)}"
    name       = prop["player_name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    team_str   = f" ({abbr(team)})" if team else ""
    return f"{emoji} {name}{team_str} \u2014 {stat_label} {prop['line']:g} \u2014 {pct_str}%"


def format_fade_line(prop: dict, team: str) -> str:
    stat_label = STAT_LABELS.get(prop["stat"], prop["stat"].upper())
    over_pct   = prop["hit_rate_overall"]
    under_pct  = round(100 - over_pct, 1)
    pct_str    = f"{under_pct:.1f}".rstrip("0").rstrip(".") if under_pct % 1 else f"{int(under_pct)}"
    name       = prop["player_name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    team_str   = f" ({abbr(team)})" if team else ""
    return f"\U0001f53b {name}{team_str} \u2014 u{stat_label} {prop['line']:g} \u2014 {pct_str}%"


def build_message(date_str: str, props: list, fades: list = None) -> str:
    fades = fades or []
    if not props and not fades:
        return ""

    pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    lines = [
        "\U0001f3af <b>C&amp;P Player Props \u2014 MLB</b>",
        f"\U0001f4c5 {pretty_date}",
        DIVIDER,
    ]

    games = {}
    for p in props:
        away = p.get("game_away_team") or ""
        home = p.get("game_home_team") or ""
        key  = (away, home) if (away or home) else ("Unknown", "Matchup")
        games.setdefault(key, {"props": [], "fades": []})
        games[key]["props"].append(p)

    for f in fades:
        away = f.get("game_away_team") or ""
        home = f.get("game_home_team") or ""
        key  = (away, home) if (away or home) else ("Unknown", "Matchup")
        games.setdefault(key, {"props": [], "fades": []})
        games[key]["fades"].append(f)

    game_keys = list(games.keys())
    for i, (away, home) in enumerate(game_keys):
        bucket = games[(away, home)]
        lines.append(f"\u26be <b>{abbr(away)} @ {abbr(home)}</b>")
        lines.append("")

        for p in sorted(bucket["props"], key=lambda x: x.get("hit_rate_overall", 0), reverse=True):
            team = get_player_team(p["player_name"])
            lines.append(format_line(p, team, "\U0001f7e2"))

        for f in bucket["fades"]:
            team = get_player_team(f["player_name"])
            lines.append(format_fade_line(f, team))

        lines.append("")
        if i < len(game_keys) - 1:
            lines.append(DIVIDER)
            lines.append("")

    lines.append(DIVIDER)
    lines.append("<i>Culture &amp; Pulse Analytics</i>")
    lines.append("<i>For entertainment only. Bet responsibly.</i>")
    return "\n".join(lines).strip()


def send_message(text: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL, "text": text, "parse_mode": "HTML"}
    r       = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("Sent successfully")
    else:
        print(f"Failed: {r.status_code} {r.text}")


def run(dry_run: bool = False, date_override: str = None):
    setup_props_table()

    if date_override:
        try:
            datetime.strptime(date_override, "%Y-%m-%d")
            date_str = date_override
        except ValueError:
            print(f"ERROR: --date must be YYYY-MM-DD, got '{date_override}'")
            sys.exit(1)
    else:
        date_str = str(get_today_ct())
    print(f"Building MLB props alert for {date_str}...")

    props = fetch_today_props(date_str)
    fades = fetch_fade_props(date_str)
    if not props and not fades:
        print(f"No props/fades met the {MIN_GAMES}-game minimum for today. No alert sent.")
        return

    message = build_message(date_str, props, fades)
    print("\n" + "\u2500" * 40)
    print(message)
    print("\u2500" * 40 + "\n")

    if dry_run:
        print("DRY RUN — not sent.")
        return

    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN not set in environment.")
        sys.exit(1)

    send_message(message)
    time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", metavar="YYYY-MM-DD")
    args = parser.parse_args()
    run(dry_run=args.dry_run, date_override=args.date)