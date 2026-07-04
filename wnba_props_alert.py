"""
wnba_props_alert.py — Culture & Pulse Analytics
=================================================
Sends a standalone Telegram alert with today's player props,
grouped by confidence tier (Green / Yellow), pulled from the
player_props table (populated daily by fetch_prizepicks_props.py).

IMPORTANT — how tiers work:
  confidence_tier is set in prop_hit_rates.py based on hit_rate_overall
  (player's historical hit rate on THIS line) plus two adjustments:
    - situational flags (struggles vs this opponent / worse home-away /
      worse on B2B) can hold a tier down even at a high overall rate
    - off-role downgrade: a PTS prop on a player whose primary category
      isn't "scorer" (see wnba_player_categories.py) drops one tier,
      since points is the highest-variance stat for non-scorers
  Base thresholds before those adjustments:
    >= 65%        -> green
    50% - 64.9%   -> yellow
    < 50% / None  -> red
  "Hit" = actual_value > line, i.e. an OVER.

  NEW — sample size floor:
  hit_rate_overall alone is meaningless on 1-2 games (it can only be
  0% or 100%). MIN_GAMES filters those out before they ever reach the
  tier logic below, regardless of what the raw rate says.

Fade signal (unders):
  All prop lines are half-points (X.5), so there's no push case — a game
  either clears the line or doesn't. That means the under rate is exact,
  not approximate: under_rate = 100 - hit_rate_overall. No separate model
  needed. Props with hit_rate_overall <= 35 (i.e. under_rate >= 65) get
  surfaced in a separate "Fades" section, since a low over-rate is a real
  signal to play the under, not just noise to exclude.

Run order each day (fully automated via render.yaml):
  1. fetch_prizepicks_props.py runs on its own schedule (10 AM CT) —
     pulls today's lines from PropLine, grades them, writes to player_props
  2. wnba_props_alert.py runs shortly after (10:15 AM CT) — reads whatever
     fetch_prizepicks_props.py just wrote and sends this alert
  No manual steps required. props_today.txt / load_props.py are now a
  manual fallback only — see load_props.py's docstring.

Schema note:
  setup_props_table() is called at the top of run() so this script is
  safe to run against a database that predates the injury_status column
  (e.g. the live one on Render) — the ALTER TABLE migration lives inside
  setup_props_table() in prop_hit_rates.py.

  ⚠️ VERIFY: the queries below assume player_props has a column that
  stores the games-played sample size behind hit_rate_overall. Guessed
  name: "games_overall". Open prop_hit_rates.py / setup_props_table()
  and confirm the actual column name, then fix MIN_GAMES_COLUMN below
  if it's different (e.g. "sample_size", "games_played", "n_games").

Usage:
    py wnba_props_alert.py            # send today's alert
    py wnba_props_alert.py --dry-run  # print instead of sending
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

# ── Config ────────────────────────────────────────────────────────────────────
CENTRAL_OFFSET = -5

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"

FADE_THRESHOLD = 35  # hit_rate_overall <= this -> under_rate >= 65 -> fade candidate

# NEW — minimum games behind a hit rate before it's trusted enough to alert on.
# 1-2 games can only produce 0% or 100%, which looks like a strong signal
# but is actually a coin flip. Raise/lower based on how conservative you want
# to be — 5 is a reasonable floor to start with.
MIN_GAMES = 5
MIN_GAMES_COLUMN = "games_overall"  # ⚠️ confirm this matches your actual column name

STAT_LABELS = {
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "stl": "STL",
    "blk": "BLK",
    "3s":  "3PM",
    "pra": "PRA",
    "pr":  "PR",
    "pa":  "PA",
    "ra":  "RA",
}

# Injury statuses worth flagging inline. Wire this dict up to your real
# injury source (e.g. wnba_data.py) once that lookup exists — for now it's
# a stub so the alert doesn't break if injury data isn't passed in.
WATCH_STATUSES = {"Day-To-Day", "Questionable", "Doubtful"}
INJURY_FLAG = {
    "Day-To-Day":  "DTD",
    "Questionable": "Q",
    "Doubtful":    "D",
}


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def fetch_today_props(date_str: str):
    """Pull today's Green/Yellow (over) props, sorted by tier then hit rate descending.
    Excludes anything below MIN_GAMES sample size."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT player_name, stat, line, hit_rate_overall, confidence_tier, injury_status
        FROM player_props
        WHERE date = ? AND sport = 'wnba'
          AND confidence_tier IN ('green', 'yellow')
          AND confidence_tier != 'insufficient'
          AND hit_rate_overall IS NOT NULL
          AND {MIN_GAMES_COLUMN} >= ?
        ORDER BY
            CASE confidence_tier WHEN 'green' THEN 0 WHEN 'yellow' THEN 1 ELSE 2 END,
            hit_rate_overall DESC
    """, (date_str, MIN_GAMES))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def fetch_fade_props(date_str: str):
    """Pull today's fade (under) candidates — low over hit rate = high under rate.
    Excludes anything below MIN_GAMES sample size."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT player_name, stat, line, hit_rate_overall, injury_status
        FROM player_props
        WHERE date = ? AND sport = 'wnba'
          AND hit_rate_overall IS NOT NULL
          AND hit_rate_overall <= ?
          AND confidence_tier != 'insufficient'
          AND {MIN_GAMES_COLUMN} >= ?
        ORDER BY hit_rate_overall ASC
    """, (date_str, FADE_THRESHOLD, MIN_GAMES))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def format_line(prop: dict, seen_players: set) -> str:
    stat_label = STAT_LABELS.get(prop["stat"], prop["stat"].upper())
    pct        = prop["hit_rate_overall"]
    pct_str    = f"{pct:.1f}".rstrip("0").rstrip(".") if pct % 1 else f"{int(pct)}"
    name       = (prop["player_name"]
                  .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    flag = ""
    status = prop.get("injury_status")
    if status in WATCH_STATUSES and prop["player_name"] not in seen_players:
        flag = f" \u26a0\ufe0f {INJURY_FLAG.get(status, status)}"

    seen_players.add(prop["player_name"])
    return f"\u2022 {name} {stat_label} {prop['line']:g} \u2014 {pct_str}%{flag}"


def format_fade_line(prop: dict, seen_players: set) -> str:
    stat_label = STAT_LABELS.get(prop["stat"], prop["stat"].upper())
    over_pct   = prop["hit_rate_overall"]
    under_pct  = round(100 - over_pct, 1)
    pct_str    = f"{under_pct:.1f}".rstrip("0").rstrip(".") if under_pct % 1 else f"{int(under_pct)}"
    name       = (prop["player_name"]
                  .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    flag = ""
    status = prop.get("injury_status")
    if status in WATCH_STATUSES and prop["player_name"] not in seen_players:
        flag = f" \u26a0\ufe0f {INJURY_FLAG.get(status, status)}"

    seen_players.add(prop["player_name"])
    return f"\U0001f53b {name} u{stat_label} {prop['line']:g} \u2014 {pct_str}%{flag}"


def build_message(date_str: str, props: list, fades: list = None) -> str:
    fades = fades or []
    if not props and not fades:
        return ""

    green  = [p for p in props if p["confidence_tier"] == "green"]
    yellow = [p for p in props if p["confidence_tier"] == "yellow"]

    pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    lines = [
        "\U0001f3af <b>C&amp;P Player Props \u2014 WNBA</b>",
        f"\U0001f4c5 {pretty_date}",
        "",
    ]

    seen = set()

    if green:
        lines.append("\U0001f7e2 <b>Green (play these):</b>")
        for p in green:
            lines.append(format_line(p, seen))
        lines.append("")

    if yellow:
        lines.append("\U0001f7e1 <b>Yellow (monitor):</b>")
        for p in yellow:
            lines.append(format_line(p, seen))
        lines.append("")

    if fades:
        lines.append("\U0001f53b <b>Fades (play the under):</b>")
        for p in fades:
            lines.append(format_fade_line(p, seen))
        lines.append("")

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
    # Self-heal schema first — safe on a fresh DB or one that predates
    # the injury_status column (e.g. the live one on Render).
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
    print(f"Building props alert for {date_str}...")

    props = fetch_today_props(date_str)
    fades = fetch_fade_props(date_str)
    if not props and not fades:
        print(f"No props/fades met the {MIN_GAMES}-game minimum for today. No alert sent.")
        return

    message = build_message(date_str, props, fades)
    print("\n" + "─" * 40)
    print(message)
    print("─" * 40 + "\n")

    if dry_run:
        print("DRY RUN — not sent.")
        return

    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN not set in environment.")
        sys.exit(1)

    send_message(message)
    time.sleep(2)  # match existing alert pacing


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending to Telegram")
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Preview alert for a specific date instead of today")
    args = parser.parse_args()
    run(dry_run=args.dry_run, date_override=args.date)
