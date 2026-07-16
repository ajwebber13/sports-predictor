"""
edge_finder_parlay.py — Culture & Pulse Analytics
====================================================
Combines Edge Finder's top picks into a real multi-leg parlay price.

This does NOT need live odds API integration (the thing that gated
this on the original roadmap) — PropLine already captures real market
odds (over_odds/under_odds) on every prop at fetch time, same data
Edge Finder itself already uses. This just combines legs that already
have real prices, using the exact American-odds-via-decimal math
pick_of_the_day.py already built and validated for its 2-leg game+prop
parlay (american_to_decimal/decimal_to_american/combine_parlay_odds,
mirrored here rather than reinvented, generalized from 2 legs to N).

What this deliberately does NOT do:
  - No correlation adjustment between legs (e.g. two props from the
    same game aren't down-weighted for being correlated outcomes).
    Real correlation modeling is a separate, harder problem — this
    prices the parlay as independent legs, same simplifying assumption
    every public parlay calculator makes, not hidden here.
  - No stake sizing / bankroll recommendation — purely shows the price
    and payout on a flat 1-unit stake, same convention as the rest of
    the platform's ROI reporting.

Usage:
    py edge_finder_parlay.py --date 2026-07-15 --sport wnba --legs 3
"""

import os
import sys
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from edge_finder import get_edge_finder, SUPPORTED_SPORTS


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


def build_parlay(picks: list, legs: int) -> dict:
    """Takes Edge Finder's already-ranked, already-guardrailed picks
    and builds a parlay from the top N that actually have real odds on
    the picked direction. A pick with no captured odds for its
    direction is skipped, not defaulted to a guessed number — a parlay
    leg with a fabricated price is worse than one leg short."""
    eligible = []
    for p in picks:
        odds = p.get("over_odds") if p["projection_direction"] == "over" else p.get("under_odds")
        if odds is None:
            continue
        eligible.append({**p, "leg_odds": odds})
        if len(eligible) == legs:
            break

    if len(eligible) < legs:
        return {
            "legs": eligible,
            "requested_legs": legs,
            "actual_legs": len(eligible),
            "parlay_odds": None,
            "payout_per_unit": None,
            "error": f"Only {len(eligible)} of {legs} requested legs had real odds available.",
        }

    odds_list = [leg["leg_odds"] for leg in eligible]
    parlay_odds = combine_parlay_odds(odds_list)
    payout = american_to_decimal(parlay_odds) - 1  # profit per 1 unit staked

    return {
        "legs": eligible,
        "requested_legs": legs,
        "actual_legs": len(eligible),
        "parlay_odds": parlay_odds,
        "payout_per_unit": round(payout, 2),
        "error": None,
    }


def format_parlay_report(date: str, sport: str, parlay: dict) -> str:
    if parlay["error"] and not parlay["legs"]:
        return f"No parlay for {sport.upper()} on {date}: {parlay['error']}"

    lines = [f"\U0001F3B0 EDGE FINDER PARLAY \u2014 {sport.upper()} ({date})", ""]
    for i, leg in enumerate(parlay["legs"], 1):
        direction_label = "Over" if leg["projection_direction"] == "over" else "Under"
        odds_str = f"+{leg['leg_odds']}" if leg["leg_odds"] > 0 else str(leg["leg_odds"])
        lines.append(
            f"  Leg {i}: {leg['player_name']} {leg['stat'].upper()} {direction_label} "
            f"{leg['line']} ({odds_str})  \u2014 Edge Score {leg['edge_score']}"
        )

    if parlay["error"]:
        lines.append("")
        lines.append(f"  Incomplete: {parlay['error']}")
    else:
        price_str = f"+{parlay['parlay_odds']}" if parlay["parlay_odds"] > 0 else str(parlay["parlay_odds"])
        lines.append("")
        lines.append(f"  Combined price: {price_str}")
        lines.append(f"  $1 staked -> ${parlay['payout_per_unit'] + 1:.2f} return (+${parlay['payout_per_unit']:.2f} profit)")
        lines.append("")
        lines.append("  Independent-leg pricing, no correlation adjustment. For entertainment only.")

    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build a parlay from today's top Edge Finder picks")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--sport", default="wnba", choices=SUPPORTED_SPORTS)
    parser.add_argument("--legs", type=int, default=2, choices=[2, 3, 4], help="Number of parlay legs (2-4)")
    parser.add_argument("--pool", type=int, default=10, help="How many top-ranked picks to draw legs from (default 10)")
    args = parser.parse_args()

    picks = get_edge_finder(args.date, sport=args.sport, top_n=args.pool)
    parlay = build_parlay(picks, legs=args.legs)
    print(format_parlay_report(args.date, args.sport, parlay))
