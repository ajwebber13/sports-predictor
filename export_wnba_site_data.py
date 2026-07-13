"""
export_wnba_site_data.py — Culture & Pulse Sports Intelligence
================================================================
Wires ranking_engine.py's real WNBA output — plus wnba_game_results.py's
real W-L record — into the site's data/wnba-rankings.json, using the
site's existing per-field source/confidence convention (real fields get
source=<engine name>/confidence="high", unbuilt fields keep
source="placeholder"/confidence="low"). No single top-level
"metadata" block — every field carries its own provenance, so a real
number never gets displayed with the same confidence as a placeholder.

WHAT'S REAL:
    elo, form, schedule_strength (sos), power_score, rank  — ranking_engine.py
    record (wins/losses)                                   — wnba_game_results.py's
                                                               get_team_record(), a real
                                                               count against team_game_results,
                                                               not an approximation
    defense                                                — real only where WNBA's
                                                               efficiency mapping produced
                                                               a value for that team
                                                               (components.efficiency_is_real_data)

WHAT'S STILL A GAP:
    trend        — diffed against the PREVIOUS committed
                   wnba-rankings.json (ranking_engine has no memory of
                   yesterday's rank).
    strengths    — reuses the exact wording logic from
                   ranking_engine.py's own __main__ CLI printout
                   (sos_word, small-sample flag, streak) — same real
                   numbers, not new text.
    offense,
    rebounding   — no backend source exists yet. Left as placeholder.
                   Do not fill these with invented numbers.

FRONTEND NOTE: `record` changed shape from a plain string
("15-5") to a field-tagged object ({"value": "15-5", "source":...,
"confidence":...}) to match every other rating field. wnba.html and
team.html need updating to read record.value instead of record
directly — that's the next step (site wiring), not done in this file.

Run manually:
    py export_wnba_site_data.py --site-repo-path /path/to/cp-sports-site

Automated via GitHub Actions (see export_wnba_site_data.yml) — same
nightly-push-to-cp-site pattern as publish_performance_summary.py and
pick_of_the_day.py's export_daily_intelligence().
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ranking_engine import get_rankings
from wnba_game_results import get_team_record

SPORT = "wnba"


def slugify(team_name: str) -> str:
    s = team_name.lower()
    s = s.replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def generate_strengths(team_result: dict) -> list:
    """Same wording rules as ranking_engine.py's __main__ block —
    kept in sync deliberately rather than reinvented here. Only
    describes real numbers already in the result; no invented claims."""
    raw = team_result["raw"]
    components = team_result["components"]
    strengths = []

    sos_word = (
        "easier than average" if raw["schedule_difficulty"] is not None and raw["schedule_difficulty"] < -5
        else "harder than average" if raw["schedule_difficulty"] is not None and raw["schedule_difficulty"] > 5
        else "about average"
    )
    if raw["schedule_difficulty"] is not None and raw["schedule_difficulty"] > 5:
        strengths.append(f"Faced a schedule {sos_word} — Power Score holds up despite the tougher slate")

    streak = raw["current_streak"]
    if streak and streak.get("length"):
        streak_word = "win" if streak.get("type") == "win" else "loss"
        strengths.append(f"Currently riding a {streak['length']}-game {streak_word} streak")

    if components.get("efficiency_is_real_data") and components["efficiency"] >= 75:
        strengths.append("Top-tier defensive efficiency (real defense-rating data)")

    if raw["elo_games_played"] < 10:
        strengths.append(f"Small sample so far ({raw['elo_games_played']} games) — ranking has room to move")

    if not strengths:
        strengths.append("No standout factor yet — power score driven by a balanced profile")

    return strengths


def build_ranking_entry(team_result: dict, prev_rank_by_slug: dict) -> dict:
    team = team_result["team"]
    slug = slugify(team)
    components = team_result["components"]

    prev_rank = prev_rank_by_slug.get(slug)
    if prev_rank is None:
        direction, movement = "flat", 0
    else:
        movement = prev_rank - team_result["rank"]
        direction = "up" if movement > 0 else "down" if movement < 0 else "flat"

    efficiency_is_real = components.get("efficiency_is_real_data", False)
    record = get_team_record(team, sport=SPORT)

    return {
        "rank": team_result["rank"],
        "team": team,
        "slug": slug,
        "record": {
            "value": record["record"],
            "source": record["source"],
            "confidence": record["confidence"],
        },
        "ratings": {
            "elo": {"value": team_result["raw"]["adjusted_elo"], "source": "ranking_engine", "confidence": "high"},
            "form": {"value": components["form"], "source": "ranking_engine", "confidence": "high"},
            "offense": {"value": None, "source": "placeholder", "confidence": "low"},
            "defense": {
                "value": components["efficiency"],
                "source": "ranking_engine" if efficiency_is_real else "placeholder",
                "confidence": "high" if efficiency_is_real else "low",
            },
            "rebounding": {"value": None, "source": "placeholder", "confidence": "low"},
            "schedule_strength": {"value": components["sos"], "source": "ranking_engine", "confidence": "high"},
        },
        "power_score": team_result["power_score"],
        "trend": {"direction": direction, "movement": movement},
        "strengths": generate_strengths(team_result),
    }


def load_previous_rankings(site_repo_path: str) -> dict:
    """Reads the file we're about to overwrite, before overwriting it,
    to compute trend. Returns {} if it doesn't exist yet (first real run)."""
    path = os.path.join(site_repo_path, "data", "wnba-rankings.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r") as f:
        data = json.load(f)
    return {r["slug"]: r["rank"] for r in data.get("rankings", [])}


def export(site_repo_path: str, min_games: int = 3):
    prev_rank_by_slug = load_previous_rankings(site_repo_path)
    results = get_rankings(SPORT, min_games=min_games)

    rankings = [build_ranking_entry(r, prev_rank_by_slug) for r in results]

    output = {
        "sport": SPORT,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "note": (
            "Real data as of this export — elo, form, schedule_strength, "
            "power_score, and record are computed from live backend data "
            "(ranking_engine.py and wnba_game_results.py). defense is real "
            "only where noted per-team (WNBA has a mapped efficiency stat, "
            "not every team has enough sample yet). offense and rebounding "
            "remain placeholder — no backend source exists yet."
        ),
        "rankings": rankings,
    }

    out_path = os.path.join(site_repo_path, "data", "wnba-rankings.json")
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(rankings)} teams to {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site-repo-path", required=True, help="Local path to a cp-sports-site checkout")
    parser.add_argument("--min-games", type=int, default=3)
    args = parser.parse_args()
    export(args.site_repo_path, args.min_games)