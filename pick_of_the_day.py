"""
pick_of_the_day.py — Culture & Pulse Analytics
================================================
Sends one "lock" pick per active sport (game ML) plus one player prop
pick, all filtered to a high-confidence floor. If nothing in a sport
clears that bar today, that sport is skipped — no forced weak picks.

When exactly one game pick and one prop pick both qualify on the same
day, also builds a 2-leg parlay combining them (real American-odds
combination via decimal conversion, not additive percentage math).
If more than one sport's game pick clears the bar the same day, the
parlay is skipped rather than guessing which game to pair with the
prop — a 3+ leg combo changes the risk profile too much to build
automatically.

RESTRUCTURED 2026-07-23: this used to build ONE combined Telegram
message covering every sport's Lock/Projection plus the single
cross-sport Prop of the Day, sent to one channel. Discord is now
organized per sport instead of by content type, so build_messages()
(plural) replaces the old build_message() (singular) — content for
the same sport (a Lock, a Projection, or the Prop of the Day, since
prop_pick carries its own "sport" field) merges into ONE message for
that sport's channel; content for different sports splits into
separate messages, each sent to its own channel.

RESOLVED 2026-07-23: the parlay section (only built when exactly one
game pick and one prop pick qualify the same day) now also requires
BOTH legs to be the same sport — see build_parlay_section(). A
cross-sport parlay (e.g. a WNBA game + an MLB prop) doesn't cleanly
belong to either channel's audience, so it's simply not built rather
than attached to one channel by default. This is decided once at the
source, so the Discord message and the daily-intelligence.json export
can never disagree about whether a parlay exists.

daily-intelligence.json export is UNCHANGED — still one combined JSON
across every sport, since that feeds the website/dashboard, not
Discord, and there's no reason to split a data file by chat channel.

Run this AFTER morning_run.yml and wnba_morning_alert.yml/props have
already populated today's predictions/player_props tables — otherwise
there's nothing to select from yet.

Usage:
    py pick_of_the_day.py            # send today's picks
    py pick_of_the_day.py --dry-run  # print instead of sending
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn

CENTRAL_OFFSET = -5
# Fallback webhook, kept from the old content-type migration — used
# only for a sport with no dedicated channel yet.
DISCORD_WEBHOOK_GAME_PICKS = os.getenv("DISCORD_WEBHOOK_GAME_PICKS", "")

GAME_CONFIDENCE_FLOOR = 80.0   # model_prob must clear this
PROP_CONFIDENCE_FLOOR = 85.0   # hit_rate_overall >= this (over) or <= 100-this (fade) — raised from 80% so only the strongest signal shows, not just whatever cleared a low bar
MIN_GAMES = 5                  # same sample-size floor as wnba_props_alert.py

# Sports that should always get a "who does the model favor" line even
# on a day nothing clears GAME_CONFIDENCE_FLOOR — added 2026-07-13 per
# Drew's request that WNBA never go silent just because no game hit an
# 80%+ edge. This is a genuinely different claim than a Lock pick: a
# Lock says "the model found a real betting edge here"; a projection
# says "here's who the model thinks wins" with no edge claim attached.
# Keep these labeled distinctly in the message — never let a
# projection read like a Lock, or the confidence-bar discipline that
# already exists for real Locks gets undermined.
ALWAYS_PROJECT_SPORTS = ["wnba"]


def get_confidence_tier(model_prob: float) -> str:
    """Presentation layer only — does NOT change scoring, selection,
    or which picks qualify as a Lock vs a Projection. That logic is
    untouched; this just labels the number that's already there.

    Thresholds are on the same 0-100 percentage scale model_prob is
    actually stored on throughout this file (see GAME_CONFIDENCE_FLOOR
    above) — not 0-1.

    Deliberately means "how strongly does the model favor this
    outcome" and NOTHING about historical profitability. Confidence
    calibration is a known, unresolved issue (see performance_tracker.py's
    confidence-bucket findings — 85-89% buckets have landed at ~50%
    actual win rate, worse than <75% buckets at ~70%). Do not relabel
    High/Medium/Low as "good/okay/bad bet" until that's fixed — those
    are two different claims and conflating them would be worse than
    not having tiers at all."""
    if model_prob >= 80:
        return "High"
    elif model_prob >= 65:
        return "Medium"
    return "Low"


def get_confidence_grade(model_prob: float) -> str:
    """Letter-grade version of get_confidence_tier(), for Telegram/
    display text only — deliberately kept SEPARATE from
    get_confidence_tier(), whose High/Medium/Low output is already
    wired into daily-intelligence.json's confidence_tier field, which
    the website's CSS (.intel-tier.high/.medium/.low) matches against.
    Changing that field's values would silently break the site's
    styling. This function exists purely so the Telegram card can read
    "A+"/"B" instead, without touching that contract.

    Same underlying meaning and same caution as get_confidence_tier():
    this is "how strongly does the model favor this outcome," not a
    profitability claim — confidence calibration is still unresolved
    (see get_confidence_tier()'s docstring)."""
    if model_prob >= 90:
        return "A+"
    elif model_prob >= 80:
        return "A"
    elif model_prob >= 70:
        return "B"
    return "C"


STAT_LABELS = {
    "pts": "PTS", "reb": "REB", "ast": "AST", "stl": "STL", "blk": "BLK",
    "pr": "PR", "pa": "PA", "ra": "RA", "pra": "PRA",
    "hits": "HITS", "runs": "RUNS", "rbis": "RBIS", "hr": "HR",
}


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def american_to_decimal(odds: int) -> float:
    if odds > 0:
        return 1 + (odds / 100)
    return 1 + (100 / abs(odds))


def decimal_to_american(decimal_odds: float) -> int:
    if decimal_odds >= 2.0:
        return round((decimal_odds - 1) * 100)
    return round(-100 / (decimal_odds - 1))


def combine_parlay_odds(american_odds_list: list) -> int:
    """Combines American odds legs into a single parlay American price.
    American odds don't add — they have to go through decimal odds
    (multiply), then convert back. E.g. two -110 legs is NOT -220,
    it's +264 (decimal 1.909 * 1.909 = 3.645 -> +264)."""
    decimal_product = 1.0
    for odds in american_odds_list:
        decimal_product *= american_to_decimal(odds)
    return decimal_to_american(decimal_product)


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


def get_model_projection(sport: str, date_str: str):
    """The model's straight win projection for this sport today — NO
    confidence floor, unlike get_game_pick_of_the_day(). This answers
    "who does the model think wins", not "is there a real betting
    edge here" — those are different questions. Picks the highest
    model_prob game (most lopsided projection), not highest edge,
    since without a floor 'highest edge' can surface a coin-flip game
    with a large edge purely from a soft market line, which isn't
    what "who does the model favor" is asking."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT game, bet, odds, model_prob, edge
        FROM predictions
        WHERE date = ? AND sport = ?
        ORDER BY model_prob DESC
        LIMIT 1
    """, (date_str, sport))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None


def get_prop_of_the_day(date_str: str):
    """
    Highest-confidence prop today across ALL active sports (over or
    fade), only if it clears the floor on whichever side. Distance
    from 50% decides the winner when multiple candidates qualify.

    Previously hardcoded to sport='wnba' only, which meant a stronger
    MLB or NBA prop could never win the slot even on days WNBA had
    nothing — fixed to compete across every sport with props data.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT sport, player_name, stat, line, hit_rate_overall, games_overall,
               over_odds, under_odds
        FROM player_props
        WHERE date = ?
          AND hit_rate_overall IS NOT NULL
          AND games_overall >= ?
          AND (hit_rate_overall >= ? OR hit_rate_overall <= ?)
    """, (date_str, MIN_GAMES, PROP_CONFIDENCE_FLOOR, 100 - PROP_CONFIDENCE_FLOOR))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    if not rows:
        return None

    # Distance from 50% — furthest wins, regardless of sport or over/fade side
    best = max(rows, key=lambda r: abs(r["hit_rate_overall"] - 50))
    is_fade = best["hit_rate_overall"] <= 50
    best["side"] = "FADE (under)" if is_fade else "OVER"
    best["display_pct"] = round(100 - best["hit_rate_overall"], 1) if is_fade else round(best["hit_rate_overall"], 1)
    # under_odds applies to a FADE (under) pick, over_odds to an OVER pick
    best["prop_odds"] = best.get("under_odds") if is_fade else best.get("over_odds")
    return best


def build_parlay_section(game_picks: dict, prop_pick: dict) -> list:
    """Only builds a parlay when exactly one game pick and one prop
    pick qualified today, both have usable odds, AND they're the same
    sport. Returns an empty list (no section) otherwise — never
    guesses which game to pair with the prop when multiple sports
    cleared the bar, and (added 2026-07-23) never builds a CROSS-sport
    parlay: with Discord now organized per sport, a parlay combining
    e.g. a WNBA game with an MLB prop wouldn't cleanly belong to
    either channel's audience. This is the single choke point both
    the Discord message (build_messages()) and the
    daily-intelligence.json export (export_daily_intelligence(), via
    parlay_eligible) read from, so both automatically agree — no risk
    of the website showing a cross-sport parlay Discord doesn't."""
    if len(game_picks) != 1 or not prop_pick:
        return []

    game_sport = list(game_picks.keys())[0]
    if prop_pick.get("sport") != game_sport:
        return []

    game_odds = list(game_picks.values())[0].get("odds")
    prop_odds = prop_pick.get("prop_odds")
    if game_odds is None or prop_odds is None:
        return []

    try:
        parlay_price = combine_parlay_odds([int(game_odds), int(prop_odds)])
    except Exception:
        return []

    game = list(game_picks.values())[0]
    stat_label = STAT_LABELS.get(prop_pick["stat"], prop_pick["stat"].upper())
    price_str = f"+{parlay_price}" if parlay_price > 0 else str(parlay_price)

    return [
        "\n\U0001f517 <b>2-LEG PARLAY</b>",
        f"{game['bet']} ({game['odds']:+d})",
        f"+ {prop_pick['player_name']} {prop_pick['side']} {stat_label} {prop_pick['line']:g} ({int(prop_odds):+d})",
        f"\U0001f4b0 Combined: {price_str}",
    ]


DAILY_INTELLIGENCE_PATH = "daily-intelligence.json"


def export_daily_intelligence(date_str: str, game_picks: dict, model_projections: dict,
                               prop_pick: dict, parlay_lines: list) -> dict:
    """Structures the SAME data build_messages() renders into Telegram
    text, as one JSON file — the single source Telegram, the website,
    and Streamlit should all read from, instead of each independently
    re-deriving locks/projections/props (same reasoning as reusing
    team_form_engine.py's fields instead of rebuilding them elsewhere).
    This function does not query the database itself — it only
    reshapes data already fetched by run(), so it can never disagree
    with what the Telegram messages actually said. UNCHANGED by the
    2026-07-23 per-sport-channel restructure — still one combined
    JSON, since this feeds the website/dashboard, not Discord."""
    locks = [
        {
            "sport": sport,
            "game": pick["game"],
            "pick": pick["bet"],
            "odds": pick["odds"],
            "confidence": round(pick["model_prob"], 1),
            "confidence_tier": get_confidence_tier(pick["model_prob"]),
            "confidence_grade": get_confidence_grade(pick["model_prob"]),
            "edge_pct": round(pick["edge"], 1),
        }
        for sport, pick in game_picks.items()
    ]

    projections = [
        {
            "sport": sport,
            "game": proj["game"],
            "favorite": proj["bet"],
            "win_probability": round(proj["model_prob"], 1),
            "confidence_tier": get_confidence_tier(proj["model_prob"]),
            "confidence_grade": get_confidence_grade(proj["model_prob"]),
        }
        for sport, proj in model_projections.items()
    ]

    props = []
    if prop_pick:
        props.append({
            "sport": prop_pick["sport"],
            "player": prop_pick["player_name"],
            "stat": STAT_LABELS.get(prop_pick["stat"], prop_pick["stat"].upper()),
            "line": prop_pick["line"],
            "side": prop_pick["side"],
            "historical_hit_rate_pct": prop_pick["display_pct"],
            "games_sampled": prop_pick["games_overall"],
            "confidence_tier": get_confidence_tier(prop_pick["display_pct"]),
            "confidence_grade": get_confidence_grade(prop_pick["display_pct"]),
        })

    return {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "locks": locks,
        "projections": projections,
        "props": props,
        "parlay_eligible": bool(parlay_lines),
    }


def build_messages(date_str: str, game_picks: dict, prop_pick: dict, model_projections: dict = None) -> dict:
    """Returns {sport: message_text} — one message per sport that has
    content today, instead of one combined string. Content for the
    SAME sport (a Lock, a Projection, and/or the Prop of the Day, since
    prop_pick carries its own "sport" field) merges into one message
    for that sport's channel; different sports split into separate
    messages. See module docstring for the parlay-attachment judgment
    call."""
    model_projections = model_projections or {}
    pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    parlay_lines = build_parlay_section(game_picks, prop_pick)
    # Parlay only ever exists when exactly one game pick qualified —
    # that pick's sport is the anchor leg, so the parlay attaches there.
    parlay_sport = list(game_picks.keys())[0] if (parlay_lines and len(game_picks) == 1) else None

    sections = {}  # sport -> list of blocks, each block a list of lines

    def add(sport, block_lines):
        sections.setdefault(sport, []).append(block_lines)

    for sport, pick in game_picks.items():
        block = [
            f"\U0001f3c6 <b>{sport.upper()} PICK</b>",
            f"{pick['game']}",
            f"\u2705 {pick['bet']} ({pick['odds']})",
            f"\U0001f4ca {pick['model_prob']:.1f}% confidence",
            f"\U0001f525 Confidence: {get_confidence_grade(pick['model_prob'])}",
            f"\U0001f4c8 Edge: +{pick['edge']:.1f}%",
        ]
        if sport == parlay_sport:
            block.extend(parlay_lines)
        add(sport, block)

    for sport, proj in model_projections.items():
        # Deliberately different framing from a Lock pick above — no
        # checkmark, no "Edge" claim, no implication this cleared any
        # bar. Just "here's who the model favors, and how strongly."
        block = [
            f"\U0001f3af <b>{sport.upper()} MODEL PROJECTION</b>",
            f"{proj['game']}",
            f"Model favors: {proj['bet']}",
            f"\U0001f4ca Win Probability: {proj['model_prob']:.1f}%",
            f"\u2696\ufe0f Confidence: {get_confidence_grade(proj['model_prob'])}",
            "<i>No qualifying betting edge today \u2014 projection only, not a Lock.</i>",
        ]
        add(sport, block)

    if prop_pick:
        sport = prop_pick["sport"]
        stat_label = STAT_LABELS.get(prop_pick["stat"], prop_pick["stat"].upper())
        block = [
            "\U0001f3af <b>PROP OF THE DAY</b>",
            f"{prop_pick['player_name']} \u2014 {prop_pick['side']} {stat_label} {prop_pick['line']:g}",
            f"\U0001f4ca {prop_pick['display_pct']}% historical rate ({prop_pick['games_overall']} games)",
            f"\U0001f525 Confidence: {get_confidence_grade(prop_pick['display_pct'])}",
        ]
        add(sport, block)

    messages = {}
    for sport, blocks in sections.items():
        lines = [
            "\U0001f512 <b>C&amp;P LOCK OF THE DAY</b>",
            f"\U0001f4c5 {pretty_date}",
            "\u2501" * 20,
        ]
        for block in blocks:
            lines.append("")
            lines.extend(block)
        lines.append("\n" + "\u2501" * 20)
        lines.append("<i>Culture &amp; Pulse Analytics</i>")
        lines.append("<i>For entertainment only. Bet responsibly.</i>")
        messages[sport] = "\n".join(lines).strip()

    return messages


def send_message(text: str, sport: str):
    from discord_alerts import send_discord_message, html_to_discord_markdown, get_webhook_for_sport
    webhook = get_webhook_for_sport(sport) or DISCORD_WEBHOOK_GAME_PICKS
    send_discord_message(html_to_discord_markdown(text), webhook_url=webhook)


def run(dry_run: bool = False):
    date_str = str(get_today_ct())
    print(f"Building Pick of the Day for {date_str}...")

    active_sports = ["nfl", "cfb", "ncaab", "wnba", "nba", "mlb"]
    game_picks = {}
    for sport in active_sports:
        pick = get_game_pick_of_the_day(sport, date_str)
        if pick:
            game_picks[sport] = pick

    # For sports in ALWAYS_PROJECT_SPORTS, if they didn't already earn
    # a real Lock pick above, still surface a straight model
    # projection so that sport never goes silent for the day.
    model_projections = {}
    for sport in ALWAYS_PROJECT_SPORTS:
        if sport in game_picks:
            continue  # already has a real Lock — don't also show a redundant projection
        proj = get_model_projection(sport, date_str)
        if proj:
            model_projections[sport] = proj

    prop_pick = get_prop_of_the_day(date_str)
    parlay_lines = build_parlay_section(game_picks, prop_pick)

    intelligence = export_daily_intelligence(date_str, game_picks, model_projections, prop_pick, parlay_lines)
    with open(DAILY_INTELLIGENCE_PATH, "w") as f:
        json.dump(intelligence, f, indent=2)
    print(f"Wrote {DAILY_INTELLIGENCE_PATH} "
          f"({len(intelligence['locks'])} lock(s), {len(intelligence['projections'])} projection(s), "
          f"{len(intelligence['props'])} prop(s))")

    messages = build_messages(date_str, game_picks, prop_pick, model_projections)
    if not messages:
        print("Nothing cleared the confidence bar today — no message sent.")
        return

    for sport, message in messages.items():
        print("\n" + "\u2500" * 40)
        print(f"[{sport.upper()}]")
        print(message)
        print("\u2500" * 40 + "\n")

        if dry_run:
            continue

        send_message(message, sport)

    if dry_run:
        print("DRY RUN — not sent.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
