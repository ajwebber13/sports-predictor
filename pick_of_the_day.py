"""
pick_of_the_day.py — Culture & Pulse Analytics
================================================
Sends one "lock" pick per active sport (game ML) plus one player prop
pick, all filtered to >= 80% confidence. If nothing in a sport clears
that bar today, that sport is skipped — no forced weak picks.

Run this AFTER morning_run.yml and wnba_morning_alert.yml/props have
already populated today's predictions/player_props tables — otherwise
there's nothing to select from yet.

Usage:
    py pick_of_the_day.py            # send today's picks
    py pick_of_the_day.py --dry-run  # print instead of sending
"""

import os
import sys
import argparse
import requests
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn

CENTRAL_OFFSET = -5
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"

GAME_CONFIDENCE_FLOOR = 80.0   # model_prob must clear this
PROP_CONFIDENCE_FLOOR = 80.0   # hit_rate_overall >= this (over) or <= 100-this (fade)
MIN_GAMES = 5                  # same sample-size floor as wnba_props_alert.py

STAT_LABELS = {
    "pts": "PTS", "reb": "REB", "ast": "AST", "stl": "STL", "blk": "BLK",
    "pr": "PR", "pa": "PA", "ra": "RA", "pra": "PRA",
}


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def get_game_pick_of_the_day(sport: str, date_str: str):
    """Highest-edge game pick for this sport today, only if model_prob >= floor."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT game, bet, odds, model_prob, edge
        FROM predictions
        WHERE date = ? AND sport = ? AND model_prob >= ?
        ORDER BY edge DESC
        LIMIT 1
    """, (date_str, sport, GAME_CONFIDENCE_FLOOR))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_prop_of_the_day(date_str: str):
    """
    Highest-confidence prop today (over or fade), only if it clears
    the 80% floor on whichever side. Distance from 50% decides the
    winner when both an over and a fade candidate qualify.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT player_name, stat, line, hit_rate_overall, games_overall
        FROM player_props
        WHERE date = ? AND sport = 'wnba'
          AND hit_rate_overall IS NOT NULL
          AND games_overall >= ?
          AND (hit_rate_overall >= ? OR hit_rate_overall <= ?)
    """, (date_str, MIN_GAMES, PROP_CONFIDENCE_FLOOR, 100 - PROP_CONFIDENCE_FLOOR))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if not rows:
        return None

    # Distance from 50% — furthest wins, regardless of over/fade side
    best = max(rows, key=lambda r: abs(r["hit_rate_overall"] - 50))
    is_fade = best["hit_rate_overall"] <= 50
    best["side"] = "FADE (under)" if is_fade else "OVER"
    best["display_pct"] = round(100 - best["hit_rate_overall"], 1) if is_fade else round(best["hit_rate_overall"], 1)
    return best


def build_message(date_str: str, game_picks: dict, prop_pick: dict) -> str:
    pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    lines = [
        "\U0001f512 <b>C&amp;P LOCK OF THE DAY</b>",
        f"\U0001f4c5 {pretty_date}",
        "\u2501" * 20,
    ]

    if not game_picks and not prop_pick:
        return ""

    for sport, pick in game_picks.items():
        lines.append(f"\n\U0001f3c6 <b>{sport.upper()} PICK</b>")
        lines.append(f"{pick['game']}")
        lines.append(f"\u2705 {pick['bet']} ({pick['odds']})")
        lines.append(f"\U0001f4ca {pick['model_prob']:.1f}% confidence \u2014 Edge +{pick['edge']:.1f}%")
        

    if prop_pick:
        stat_label = STAT_LABELS.get(prop_pick["stat"], prop_pick["stat"].upper())
        lines.append(f"\n\U0001f3af <b>PROP OF THE DAY</b>")
        lines.append(f"{prop_pick['player_name']} \u2014 {prop_pick['side']} {stat_label} {prop_pick['line']:g}")
        lines.append(f"\U0001f4ca {prop_pick['display_pct']}% historical rate ({prop_pick['games_overall']} games)")

    lines.append("\n" + "\u2501" * 20)
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


def run(dry_run: bool = False):
    date_str = str(get_today_ct())
    print(f"Building Pick of the Day for {date_str}...")

    active_sports = ["nfl", "cfb", "ncaab", "wnba", "nba", "mlb"]
    game_picks = {}
    for sport in active_sports:
        pick = get_game_pick_of_the_day(sport, date_str)
        if pick:
            game_picks[sport] = pick

    prop_pick = get_prop_of_the_day(date_str)

    message = build_message(date_str, game_picks, prop_pick)
    if not message:
        print("Nothing cleared the 80% bar today — no message sent.")
        return

    print("\n" + "\u2500" * 40)
    print(message)
    print("\u2500" * 40 + "\n")

    if dry_run:
        print("DRY RUN — not sent.")
        return

    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN not set.")
        sys.exit(1)

    send_message(message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
