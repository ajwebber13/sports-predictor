"""
edge_finder_alert.py — Culture & Pulse Analytics
=================================================
Sends the daily "Edge Finder Top N" Telegram post — the composite
ranking from edge_finder.py, formatted for the channel. This is the
content-layer piece of Edge Finder: the engine (edge_finder.py) and the
API (/props/edge-finder) already existed, this just publishes it.

Mirrors wnba_props_alert.py's structure (config, send_message(), run(),
CLI args) so it's consistent with the rest of the alert pipeline, but
is intentionally a SEPARATE message/script, not folded into the props
alert — Edge Finder is a cross-stat ranked list (best props of the day
regardless of stat), while wnba_props_alert.py is grouped by game. They
answer different questions and would be confusing merged into one post.

Guardrails (MIN_HIT_RATE/MIN_EDGE_PCT/MIN_SAMPLE_SIZE) live in
edge_finder.py itself, not duplicated here — this script only formats
and sends whatever get_edge_finder() already decided is postable.

Usage:
    py edge_finder_alert.py                      # today's WNBA top 5
    py edge_finder_alert.py --dry-run             # print instead of sending
    py edge_finder_alert.py --sport nba --top 10  # different sport/count
    py edge_finder_alert.py --date 2026-07-15      # preview a specific date
"""

import os
import sys
import argparse
import time
import requests
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from edge_finder import get_edge_finder, log_edge_finder_picks, _defense_rank, SUPPORTED_SPORTS, \
    MIN_HIT_RATE, MIN_EDGE_PCT, MIN_SAMPLE_SIZE
from ai_prop_analyzer import generate_prop_analysis
from edge_finder_parlay import build_parlay

CENTRAL_OFFSET = -5

DISCORD_WEBHOOK_PROPS = os.getenv("DISCORD_WEBHOOK_PROPS", "")

CONFIDENCE_EMOJI = {"HIGH": "\U0001F525", "MEDIUM": "\u2705"}  # fire / check
DIVIDER = "\u2500" * 28


def get_today_ct() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).strftime("%Y-%m-%d")


def build_message(date: str, sport: str, picks: list, brief: bool = False, parlay_legs: int = 0) -> str:
    lines = [f"<b>\U0001F525 EDGE FINDER \u2014 {sport.upper()} TOP {len(picks)}</b>", ""]

    for i, p in enumerate(picks, 1):
        direction_label = "Over" if p["projection_direction"] == "over" else "Under"
        emoji = CONFIDENCE_EMOJI.get(p["confidence"], "")

        rank, total = _defense_rank(sport, p["stat"], p["opponent"], p["projection_direction"])
        matchup = f"#{rank}/{total} D vs {p['stat'].upper()}" if rank else f"vs {p['opponent']}"

        lines.append(
            f"{i}. <b>{p['player_name']}</b> {p['stat'].upper()} {direction_label} {p['line']}"
        )
        lines.append(
            f"   Edge Score: <b>{p['edge_score']}</b> {emoji} {p['confidence']}"
        )
        lines.append(
            f"   \u2705 {p['hit_rate_overall']}% ({p['games_overall']}G)  "
            f"\U0001F4C8 {p['projection_edge_pct']:+.1f}%  "
            f"\U0001F6E1 {matchup}"
        )
        if not brief:
            # Templated, deterministic — same numbers always produce the
            # same sentence. Not an LLM call. See ai_prop_analyzer.py.
            analysis = generate_prop_analysis(p, sport)
            lines.append(f"   <i>{analysis}</i>")
        lines.append("")

    if parlay_legs and parlay_legs > 0:
        # Draws legs from this SAME picks list, already shown above —
        # the parlay is a combination of what the audience just read,
        # not a second, separately-fetched set of players.
        parlay = build_parlay(picks, legs=parlay_legs)
        lines.append(DIVIDER)
        if parlay["error"]:
            lines.append(f"<i>Parlay unavailable today: {parlay['error']}</i>")
        else:
            price_str = f"+{parlay['parlay_odds']}" if parlay["parlay_odds"] > 0 else str(parlay["parlay_odds"])
            lines.append(f"<b>\U0001F3B0 {parlay_legs}-LEG PARLAY: {price_str}</b>")
            for leg in parlay["legs"]:
                leg_direction = "Over" if leg["projection_direction"] == "over" else "Under"
                lines.append(f"  \u2022 {leg['player_name']} {leg['stat'].upper()} {leg_direction} {leg['line']}")
            lines.append(
                f"  $1 \u2192 ${parlay['payout_per_unit'] + 1:.2f} return "
                f"(+${parlay['payout_per_unit']:.2f} profit)"
            )
            lines.append("<i>Independent-leg pricing, no correlation adjustment.</i>")
        lines.append("")

    lines.append(DIVIDER)
    lines.append(
        f"<i>Guardrails: {MIN_HIT_RATE}%+ hit rate, {MIN_EDGE_PCT}%+ edge, "
        f"{MIN_SAMPLE_SIZE}+ games. Composite score, not a guarantee.</i>"
    )
    lines.append("<i>Culture &amp; Pulse Analytics</i>")
    lines.append("<i>For entertainment only. Bet responsibly.</i>")
    return "\n".join(lines).strip()


def send_message(text: str):
    from discord_alerts import send_discord_message, html_to_discord_markdown
    send_discord_message(html_to_discord_markdown(text), webhook_url=DISCORD_WEBHOOK_PROPS)


def run(sport: str = "wnba", dry_run: bool = False, date_override: str = None, top_n: int = 5,
        brief: bool = False, parlay_legs: int = 0):
    if sport not in SUPPORTED_SPORTS:
        print(f"ERROR: unsupported sport '{sport}'. Use one of {SUPPORTED_SPORTS}.")
        sys.exit(1)

    if date_override:
        try:
            datetime.strptime(date_override, "%Y-%m-%d")
            date_str = date_override
        except ValueError:
            print(f"ERROR: --date must be YYYY-MM-DD, got '{date_override}'")
            sys.exit(1)
    else:
        date_str = get_today_ct()

    print(f"Building Edge Finder alert for {sport.upper()} {date_str}...")

    picks = get_edge_finder(date_str, sport=sport, top_n=top_n)
    if not picks:
        print(
            f"No qualifying edges for {sport.upper()} on {date_str} "
            f"(nothing cleared {MIN_HIT_RATE}% hit rate / {MIN_EDGE_PCT}%+ edge / "
            f"{MIN_SAMPLE_SIZE}+ games). No alert sent."
        )
        return

    message = build_message(date_str, sport, picks, brief=brief, parlay_legs=parlay_legs)
    print("\n" + "\u2500" * 40)
    print(message)
    print("\u2500" * 40 + "\n")

    if dry_run:
        print("DRY RUN \u2014 not sent.")
        return

    if not DISCORD_WEBHOOK_PROPS:
        print("ERROR: DISCORD_WEBHOOK_PROPS not set in environment.")
        sys.exit(1)

    send_message(message)
    time.sleep(2)  # match existing alert pacing

    # Log AFTER a real send, not before and not on dry-run — a pick that
    # was never actually sent shouldn't count in results tracking.
    try:
        n = log_edge_finder_picks(date_str, sport, picks)
        print(f"Logged {n} pick(s) to edge_finder_picks for results tracking.")
    except Exception as e:
        # Never let a logging failure look like the alert itself failed —
        # the message already sent successfully by this point.
        print(f"WARNING: alert sent, but logging to edge_finder_picks failed: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="wnba", choices=SUPPORTED_SPORTS)
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending to Telegram")
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Preview alert for a specific date instead of today")
    parser.add_argument("--top", type=int, default=5, help="How many picks to include (default 5)")
    parser.add_argument("--brief", action="store_true", help="Skip the AI Prop Analyzer sentence, just the stat line")
    parser.add_argument("--parlay-legs", type=int, default=0, choices=[0, 2, 3, 4],
                         help="Append an N-leg parlay built from these same picks (0 = no parlay, default)")
    args = parser.parse_args()
    run(sport=args.sport, dry_run=args.dry_run, date_override=args.date, top_n=args.top,
        brief=args.brief, parlay_legs=args.parlay_legs)
