"""
ai_prop_analyzer.py — Culture & Pulse Analytics
=================================================
Generates a natural-language "why" paragraph for an Edge Finder pick,
built entirely from numbers the pipeline already trusts (hit rate,
projection edge %, defense matchup, sample size) — NOT a call out to
an LLM. This matches the locked roadmap decision that the "Knowledge
Layer" should be a byproduct of each engine logging its driving
factors, not a separate NLP build.

Deliberately does NOT touch predictions.model_prob or any game-level
confidence number — that's the metric currently flagged as
uncalibrated (see sports-predictor-roadmap notes). Everything used
here is either a real historical stat (hit_rate_overall) or something
Edge Finder already validated end-to-end against live data
(projection_edge_pct, defense_factor, edge_score).

Phrasing is templated and deterministic (bucketed by magnitude, not
randomized) — same inputs always produce the same analysis, which
matters for anything that gets posted publicly and might get compared
day to day.

Usage:
    from ai_prop_analyzer import generate_prop_analysis
    from edge_finder import get_edge_finder

    picks = get_edge_finder("2026-07-15", sport="wnba", top_n=5)
    for p in picks:
        print(generate_prop_analysis(p, sport="wnba"))
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from edge_finder import _defense_rank


def _hit_rate_phrase(hit_rate: float, games: int) -> str:
    if hit_rate >= 85:
        tier = "an elite"
    elif hit_rate >= 75:
        tier = "a strong"
    else:
        tier = "a solid"
    return f"{tier} {hit_rate}% hit rate over the last {games} games"


def _edge_phrase(edge_pct: float, direction: str) -> str:
    magnitude = abs(edge_pct)
    if magnitude >= 25:
        strength = "a massive"
    elif magnitude >= 15:
        strength = "a strong"
    else:
        strength = "a real"
    side = "above" if direction == "over" else "below"
    return f"the projection sits {strength} {magnitude:.1f}% {side} the line"


def _matchup_phrase(stat: str, direction: str, opponent: str, rank, total) -> str:
    stat_label = stat.upper()
    if not rank or not total:
        return f"facing {opponent}"

    third = total / 3
    if rank <= third:
        favorability = "one of the more favorable matchups on the board"
    elif rank <= 2 * third:
        favorability = "a middle-of-the-pack matchup"
    else:
        favorability = "a tougher-than-average matchup, but the edge holds up anyway"

    return f"against {opponent}, ranked #{rank} of {total} defenses vs {stat_label} — {favorability}"


def generate_prop_analysis(pick: dict, sport: str) -> str:
    """Builds a 2-3 sentence natural-language analysis for one Edge
    Finder pick dict (same shape returned by get_edge_finder()).
    Read-only — does not call the DB or mutate the pick."""
    direction_label = "over" if pick["projection_direction"] == "over" else "under"

    rank, total = _defense_rank(sport, pick["stat"], pick["opponent"], pick["projection_direction"])
    hit_phrase = _hit_rate_phrase(pick["hit_rate_overall"], pick["games_overall"])
    edge_phrase = _edge_phrase(pick["projection_edge_pct"], pick["projection_direction"])
    matchup_phrase = _matchup_phrase(pick["stat"], pick["projection_direction"], pick["opponent"], rank, total)

    sentence_1 = (
        f"{pick['player_name']} has {hit_phrase} on the {direction_label} "
        f"{pick['line']} {pick['stat'].upper()} line, and {edge_phrase}."
    )
    sentence_2 = f"Tonight's matchup is {matchup_phrase}."

    if pick["confidence"] == "HIGH":
        closer = (
            f"With an Edge Score of {pick['edge_score']}, this is one of the stronger "
            f"plays on today's board."
        )
    else:
        closer = (
            f"Edge Score sits at {pick['edge_score']} — a real signal, though not yet at "
            f"the sample size or score needed for a HIGH-confidence label."
        )

    return f"{sentence_1} {sentence_2} {closer}"


if __name__ == "__main__":
    import argparse
    from edge_finder import get_edge_finder, SUPPORTED_SPORTS

    parser = argparse.ArgumentParser(description="Generate AI Prop Analyzer text for today's Edge Finder picks")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--sport", default="wnba", choices=SUPPORTED_SPORTS)
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    picks = get_edge_finder(args.date, sport=args.sport, top_n=args.top)
    if not picks:
        print(f"No qualifying edges for {args.sport.upper()} on {args.date}.")
    else:
        for i, p in enumerate(picks, 1):
            print(f"{i}. {p['player_name']} {p['stat'].upper()} {p['line']}")
            print(f"   {generate_prop_analysis(p, args.sport)}")
            print()
