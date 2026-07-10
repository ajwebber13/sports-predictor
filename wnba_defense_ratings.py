"""
wnba_defense_ratings.py — Culture & Pulse Analytics
=====================================================
Computes how much of a given stat each team allows, per minute, relative
to league average. Used to adjust player projections for opponent
strength — and doubles as the first piece of the Defensive Rating
column in the Rankings Engine you're planning.

factor > 1.0  → team allows MORE than average (weak defense — bump
                projections UP against them)
factor < 1.0  → team allows LESS than average (tough defense — bump
                projections DOWN against them)
factor = 1.0  → league average, or not enough games yet to trust a read

Data source: wnba_game_log's own "opponent" column. For team X, we sum
every stat put up by players who faced team X, divided by the minutes
those players played. That's "production allowed per minute" — compare
it to the league rate to get the factor.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn, rows_to_dicts as _rows_to_dicts

TABLE = "wnba_game_log"
SEASON_DEFAULT = "2026"
MIN_GAMES_FOR_DEFENSE = 5  # games faced (as the opponent) before trusting a read

_cache = {}  # {(stat, season): {team_name: factor}}

STAT_SQL = {
    "pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
    "pra": "(pts + reb + ast)", "pr": "(pts + reb)", "pa": "(pts + ast)", "ra": "(reb + ast)",
}


def get_defense_factors(stat: str, season: str = SEASON_DEFAULT, use_cache: bool = True) -> dict:
    """Returns {team_name: factor} for every team with enough games."""
    stat_sql = STAT_SQL.get(stat)
    if not stat_sql:
        return {}

    cache_key = (stat, season)
    if use_cache and cache_key in _cache:
        return _cache[cache_key]

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute(f"""
            SELECT opponent as team, SUM({stat_sql}) as stat_total,
                   SUM(minutes) as minutes_total, COUNT(DISTINCT date) as games
            FROM {TABLE}
            WHERE date LIKE ? AND opponent IS NOT NULL AND opponent != ''
            GROUP BY opponent
        """, (f"{season}%",))
        rows = _rows_to_dicts(c, c.fetchall())

        c.execute(f"""
            SELECT SUM({stat_sql}) as stat_total, SUM(minutes) as minutes_total
            FROM {TABLE}
            WHERE date LIKE ?
        """, (f"{season}%",))
        league_row = c.fetchone()
        league_rows = _rows_to_dicts(c, [league_row]) if league_row else []
        league = league_rows[0] if league_rows else {}
    except Exception as e:
        print(f"  ⚠️  defense_ratings: couldn't compute for '{stat}' ({e})")
        conn.close()
        return {}
    conn.close()

    league_minutes = league.get("minutes_total") or 0
    league_stat    = league.get("stat_total") or 0
    if league_minutes <= 0 or league_stat <= 0:
        return {}
    league_rate = league_stat / league_minutes

    factors = {}
    for r in rows:
        if (r["games"] or 0) < MIN_GAMES_FOR_DEFENSE or not r["minutes_total"]:
            continue
        team_rate = r["stat_total"] / r["minutes_total"]
        factors[r["team"]] = round(team_rate / league_rate, 3)

    if use_cache:
        _cache[cache_key] = factors
    return factors


def get_defense_factor(team_name: str, stat: str, season: str = SEASON_DEFAULT) -> float:
    """Single-team lookup. Returns 1.0 (neutral) if unavailable — never
    blocks a projection just because a rating isn't ready yet."""
    if not team_name:
        return 1.0
    factors = get_defense_factors(stat, season=season)
    return factors.get(team_name, 1.0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Show WNBA defense-allowed ratings for a stat")
    parser.add_argument("--stat", required=True, choices=list(STAT_SQL.keys()))
    parser.add_argument("--season", default=SEASON_DEFAULT)
    args = parser.parse_args()

    factors = get_defense_factors(args.stat, season=args.season)
    if not factors:
        print(f"No defense data yet for '{args.stat}' (need {MIN_GAMES_FOR_DEFENSE}+ games per team).")
    else:
        print(f"\n{args.stat.upper()} allowed vs league average (>1.0 = weak D, <1.0 = tough D)\n")
        for team, factor in sorted(factors.items(), key=lambda x: -x[1]):
            print(f"  {team:<24} {factor}")
