"""
nfl_defense_ratings.py — Culture & Pulse Analytics
=====================================================
Computes how much of a given stat each team allows, per game, relative
to league average. Used to adjust player projections for opponent
strength — same purpose as wnba_defense_ratings.py.

factor > 1.0  → team allows MORE than average (weak defense — bump
                projections UP against them)
factor < 1.0  → team allows LESS than average (tough defense — bump
                projections DOWN against them)
factor = 1.0  → league average, or not enough games yet to trust a read

ONE REAL DIFFERENCE FROM THE WNBA VERSION: WNBA normalizes by minutes
(players log different amounts of court time per game, so "allowed per
minute" is the fair comparison). nfl_game_log has no per-play tracking,
so this normalizes by GAMES instead — "opponent allows per game" vs
"league average per game" — exactly matching how real NFL defensive
stats (e.g. "passing yards allowed per game") are already reported.

Data source: nfl_game_log's own "opponent" column, same pattern as
WNBA — for team X, sum every stat put up by players who faced team X,
divided by the number of distinct games X played.

NOTE: NFL's season spans two calendar years (Sept-Feb), same as NBA —
a "2026%" date prefix would silently drop every Sept-Dec 2025 game.
Uses the whole table rather than a season-year filter, same fix
already applied in star_players.py's spans_calendar_years handling.
Revisit if/when multiple NFL seasons' worth of history pile up in one
table and a real season boundary is needed.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn

TABLE = "nfl_game_log"
MIN_GAMES_FOR_DEFENSE = 3  # games faced (as the opponent) before trusting a read — lower than WNBA's 5 since NFL is a 17-game season

_cache = {}  # {stat: {team_name: factor}}

STAT_SQL = {
    "passing_yards":       "passing_yards",
    "passing_tds":         "passing_tds",
    "passing_attempts":    "passing_attempts",
    "passing_completions": "passing_completions",
    "rushing_yards":       "rushing_yards",
    "rushing_attempts":    "rushing_attempts",
    "rushing_tds":         "rushing_tds",
    "receptions":          "receptions",
    "receiving_yards":     "receiving_yards",
    "receiving_tds":       "receiving_tds",
}


def get_defense_factors(stat: str, use_cache: bool = True) -> dict:
    """Returns {team_name: factor} for every team with enough games."""
    stat_sql = STAT_SQL.get(stat)
    if not stat_sql:
        return {}

    if use_cache and stat in _cache:
        return _cache[stat]

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute(f"""
            SELECT opponent as team, SUM({stat_sql}) as stat_total,
                   COUNT(DISTINCT date) as games
            FROM {TABLE}
            WHERE opponent IS NOT NULL AND opponent != ''
            GROUP BY opponent
        """)
        rows = [dict(r) for r in c.fetchall()]
    except Exception as e:
        print(f"  ⚠️  defense_ratings: couldn't compute for '{stat}' ({e})")
        conn.close()
        return {}
    conn.close()

    # League rate = total stat allowed across every team / total games
    # played league-wide, built from the same per-team rows above rather
    # than a second query — weights every team's game count fairly.
    league_stat_total  = sum(r["stat_total"] or 0 for r in rows)
    league_games_total = sum(r["games"] or 0 for r in rows)
    if league_games_total <= 0 or league_stat_total <= 0:
        return {}
    league_rate = league_stat_total / league_games_total

    factors = {}
    for r in rows:
        if (r["games"] or 0) < MIN_GAMES_FOR_DEFENSE:
            continue
        team_rate = (r["stat_total"] or 0) / r["games"]
        factors[r["team"]] = round(team_rate / league_rate, 3)

    if use_cache:
        _cache[stat] = factors
    return factors


def get_defense_factor(team_name: str, stat: str) -> float:
    """Single-team lookup. Returns 1.0 (neutral) if unavailable — never
    blocks a projection just because a rating isn't ready yet."""
    if not team_name:
        return 1.0
    factors = get_defense_factors(stat)
    return factors.get(team_name, 1.0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Show NFL defense-allowed ratings for a stat")
    parser.add_argument("--stat", required=True, choices=list(STAT_SQL.keys()))
    args = parser.parse_args()

    factors = get_defense_factors(args.stat)
    if not factors:
        print(f"No defense data yet for '{args.stat}' (need {MIN_GAMES_FOR_DEFENSE}+ games per team).")
    else:
        print(f"\n{args.stat.upper()} allowed vs league average (>1.0 = weak D, <1.0 = tough D)\n")
        for team, factor in sorted(factors.items(), key=lambda x: -x[1]):
            print(f"  {team:<24} {factor}")
