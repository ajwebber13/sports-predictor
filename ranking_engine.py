"""
ranking_engine.py — Culture & Pulse Analytics
====================================================
Infrastructure, not a feature — combines elo_ratings.py +
strength_of_schedule.py + team_form_engine.py + sport-specific
defense_ratings modules into one power_score + rank per team.
power_rankings.py (not built yet) becomes the display layer that
just calls get_rankings(sport).

    results --> elo_ratings.py --> strength_of_schedule.py -\
            --> team_form_engine.py ----------------------------> ranking_engine.py --> power_rankings.py
            --> <sport>_defense_ratings.py ------------------/

Weighting (agreed 2026-07-11):
    40% Team Quality   = Adjusted Elo + SOS Adjustment
    25% Recent Form     = win % from team_form_engine.py
    20% Efficiency      = sport-specific defense factor (proxy — see note below)
    15% Model Confidence = avg_model_probability from team_form_engine.py

Elo reliability: elo_ratings.py stays a pure rating engine and knows
nothing about trust — that judgment lives here. games_played < 15
means the rating hasn't stabilized (see the Valkyries case, 2026-07-11:
1684 Elo after 7 games, explained by cold-start K-factor + a weak
schedule, not a real #1 team). Reliability is blended toward the
league-average anchor (1500), not applied as a flat multiplier on the
raw number (that would compress everyone's spread unevenly):

    reliability   = min(games_played / 15, 1.0)
    adjusted_elo  = 1500 + (raw_elo - 1500) * reliability

SOS is folded into Team Quality directly in Elo-point units
(schedule_difficulty is already an Elo-point differential from 1500),
capped at +/-SOS_ADJUSTMENT_CAP so a hard schedule can nudge the
ranking without letting it outweigh actual proven Elo strength.

Model Confidence reuses team_form_engine.py's avg_model_probability
rather than building new per-team functions in performance_tracker.py
— avoids duplicating the same picked_this_team-gated calculation in
two places (same principle already applied to keep Team Profile from
duplicating Power Rankings/Matchup Analyzer logic).

Efficiency — REAL DATA GAP, not silently worked around: the
per-sport <sport>_defense_ratings.py files use per-stat "allowed"
factors, not a single points-allowed number. WNBA and NBA both have a
"pts" stat, so Efficiency is real for those two. NFL's file only has
category stats (passing_yards, rushing_tds, etc.) — no points-allowed
proxy exists yet, so NFL (and any other unmapped sport) gets a neutral
50 for Efficiency until someone builds that mapping. See
EFFICIENCY_STAT_MAP below — extend it sport-by-sport as real defense
data becomes available, don't guess a composite stat in the meantime.

All four components are min-max normalized to 0-100 ACROSS THE LEAGUE
before weighting, since raw units aren't comparable (Elo ~1300-1700,
win% 0-1, defense factor ~0.7-1.3, model_prob 0-1).

Usage:
    py ranking_engine.py
    (prints WNBA rankings — see bottom of file)
"""

import os
import sys
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from elo_ratings import get_elo, get_games_played
from strength_of_schedule import get_strength_of_schedule
from team_form_engine import get_team_form

# Extend this as real per-sport defense data becomes available.
# Sport not listed here -> Efficiency defaults to neutral (50), not a guess.
EFFICIENCY_STAT_MAP = {
    "wnba": "pts",
    "nba": "pts",
}

RELIABILITY_GAMES_THRESHOLD = 15  # matches elo_ratings.py's own early-season K-factor cutoff
SOS_ADJUSTMENT_CAP = 50  # caps schedule_difficulty's swing on Team Quality — SOS should nudge
                          # the ranking, not let a hard schedule outweigh actual proven Elo strength


def _norm_sport(sport):
    return sport.lower() if sport else None


def _all_teams_with_elo(sport: str) -> list:
    sport = _norm_sport(sport)
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT DISTINCT team_name FROM elo_ratings WHERE sport = ?", (sport,))
    rows = c.fetchall()
    conn.close()
    return [r["team_name"] for r in rows]


def _get_efficiency_proxy(team: str, sport: str):
    """Returns a raw value where HIGHER = better defense, or None if
    this sport has no mapped defense stat yet (see EFFICIENCY_STAT_MAP).
    Defense "allowed" factor is >1.0 for weak D, <1.0 for tough D — we
    negate it so min-max normalization ranks tough defenses higher."""
    stat = EFFICIENCY_STAT_MAP.get(sport)
    if not stat:
        return None
    try:
        module = importlib.import_module(f"{sport}_defense_ratings")
        factor = module.get_defense_factor(team, stat)
    except Exception:
        return None
    if factor is None:
        return None
    return -factor


def _normalize(values: dict) -> dict:
    """Min-max normalize a {team: raw_value} dict to 0-100. If every
    team has the same value (or there's only one team), returns 50
    (neutral) for all rather than dividing by zero."""
    if not values:
        return {}
    vals = list(values.values())
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return {k: 50.0 for k in values}
    return {k: round((v - lo) / (hi - lo) * 100, 1) for k, v in values.items()}


def calculate_elo_score(team: str, sport: str) -> dict:
    """Raw Elo, games played, reliability, and the reliability-adjusted
    Elo (blended toward the 1500 league-average anchor, not a flat
    multiplier — see module docstring)."""
    elo = get_elo(team, sport)
    games_played = get_games_played(team, sport)
    reliability = round(min(games_played / RELIABILITY_GAMES_THRESHOLD, 1.0), 3)
    adjusted_elo = round(1500 + (elo - 1500) * reliability, 1)
    return {
        "elo": elo,
        "games_played": games_played,
        "reliability": reliability,
        "adjusted_elo": adjusted_elo,
    }


def get_rankings(sport: str, min_games: int = 3) -> list:
    """Full ranked list for a sport. Teams below min_games (per
    team_form_engine.py's real-game-result sample) are excluded rather
    than ranked off an insufficient sample."""
    sport = _norm_sport(sport)
    teams = _all_teams_with_elo(sport)

    raw_quality = {}
    raw_form = {}
    raw_efficiency = {}
    raw_confidence = {}
    detail = {}

    for team in teams:
        form = get_team_form(team, sport=sport, min_games=min_games)
        if form.get("insufficient_sample"):
            continue

        elo_info = calculate_elo_score(team, sport)

        sos = get_strength_of_schedule(team, sport=sport, min_games=1)
        schedule_difficulty = sos["schedule_difficulty"] if not sos.get("insufficient_sample") else 0.0
        sos_adjustment = max(min(schedule_difficulty, SOS_ADJUSTMENT_CAP), -SOS_ADJUSTMENT_CAP)

        team_quality_raw = elo_info["adjusted_elo"] + sos_adjustment
        raw_quality[team] = team_quality_raw
        raw_form[team] = form["win_percentage"]

        if form["avg_model_probability"] is not None:
            raw_confidence[team] = form["avg_model_probability"]

        eff = _get_efficiency_proxy(team, sport)
        if eff is not None:
            raw_efficiency[team] = eff

        detail[team] = {
            "elo": elo_info,
            "sos": sos,
            "sos_adjustment": sos_adjustment,
            "form": form,
        }

    quality_n = _normalize(raw_quality)
    form_n = _normalize(raw_form)
    efficiency_n = _normalize(raw_efficiency)
    confidence_n = _normalize(raw_confidence)

    results = []
    for team in raw_quality:
        eff_score = efficiency_n.get(team, 50.0)  # neutral if sport unmapped or team has no defense sample yet
        conf_score = confidence_n.get(team, 50.0)  # neutral if model never picked this team

        power_score = round(
            quality_n[team] * 0.40
            + form_n[team] * 0.25
            + eff_score * 0.20
            + conf_score * 0.15,
            1,
        )

        results.append({
            "team": team,
            "sport": sport,
            "power_score": power_score,
            "weighted_components": {
                "team_quality": round(quality_n[team] * 0.40, 1),
                "recent_form": round(form_n[team] * 0.25, 1),
                "efficiency": round(eff_score * 0.20, 1),
                "model_confidence": round(conf_score * 0.15, 1),
            },
            "components": {
                "team_quality": quality_n[team],
                "form": form_n[team],
                "efficiency": eff_score,
                "efficiency_is_real_data": team in raw_efficiency,
                "model_confidence": conf_score,
                "model_confidence_is_real_data": team in raw_confidence,
            },
            "raw": {
                "elo": detail[team]["elo"]["elo"],
                "elo_games_played": detail[team]["elo"]["games_played"],
                "elo_reliability": detail[team]["elo"]["reliability"],
                "adjusted_elo": detail[team]["elo"]["adjusted_elo"],
                "schedule_difficulty": detail[team]["sos"].get("schedule_difficulty"),
                "sos_adjustment_applied": detail[team]["sos_adjustment"],
                "avg_opponent_elo": detail[team]["sos"].get("avg_opponent_elo"),
                "win_percentage": detail[team]["form"]["win_percentage"],
                "current_streak": detail[team]["form"]["current_streak"],
            },
        })

    results.sort(key=lambda r: r["power_score"], reverse=True)
    for i, r in enumerate(results, start=1):
        r["rank"] = i

    return results


if __name__ == "__main__":
    sport_arg = sys.argv[1] if len(sys.argv) > 1 else "wnba"
    rankings = get_rankings(sport_arg)

    print(f"\n{'='*100}")
    print(f"  {sport_arg.upper()} POWER RANKINGS (v1)")
    print(f"{'='*100}")
    print(f"  {'Rank':>4}  {'Team':<24} {'Power':>7} {'Elo':>6} {'Form':>6} {'SOS':>6} {'Effic.':>7} {'Conf.':>6}")
    print(f"  {'-'*4}  {'-'*24} {'-'*7} {'-'*6} {'-'*6} {'-'*6} {'-'*7} {'-'*6}")
    for r in rankings:
        c = r["components"]
        raw = r["raw"]
        print(f"  {r['rank']:>4}  {r['team']:<24} {r['power_score']:>7} "
              f"{c['team_quality']:>6} {c['form']:>6} {raw['sos_adjustment_applied']:>+6} "
              f"{c['efficiency']:>7} {c['model_confidence']:>6}")

    print(f"\n{'='*100}")
    print("  FLAGS")
    print(f"{'='*100}")
    for r in rankings:
        c = r["components"]
        raw = r["raw"]
        small_sample = raw["elo_games_played"] < RELIABILITY_GAMES_THRESHOLD
        sos_word = ("easier than average" if raw["schedule_difficulty"] < -5
                    else "harder than average" if raw["schedule_difficulty"] > 5
                    else "about average")
        print(f"\n  {r['team']}")
        print(f"    Small Sample:      {'Yes (' + str(raw['elo_games_played']) + ' games)' if small_sample else 'No'}")
        print(f"    SOS:               {sos_word} ({raw['schedule_difficulty']:+})")
        print(f"    Efficiency Data:   {'Real' if c['efficiency_is_real_data'] else 'Neutral placeholder (no data yet)'}")
        print(f"    Confidence Data:   {'Real' if c['model_confidence_is_real_data'] else 'Neutral placeholder (model never picked this team)'}")
        print(f"    Weighted:          quality={r['weighted_components']['team_quality']} "
              f"form={r['weighted_components']['recent_form']} "
              f"efficiency={r['weighted_components']['efficiency']} "
              f"confidence={r['weighted_components']['model_confidence']}")
    print(f"\n{'='*100}\n")