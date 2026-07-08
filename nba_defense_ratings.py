"""
nba_defense_ratings.py — Culture & Pulse Analytics
=====================================================
NBA equivalent of wnba_defense_ratings.py. Same math (minutes as the
volume metric, same as WNBA), but no season-year prefix filter — the
NBA season runs Oct-June across two calendar years, so nba_game_log's
whole table represents one season until it's wiped for the next one.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn

TABLE = "nba_game_log"
MIN_GAMES_FOR_DEFENSE = 5  # games faced (as the opponent) before trusting a read

_cache = {}  # {stat: {team_name: factor}}

STAT_SQL = {
    "pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
    "pra": "(pts + reb + ast)", "pr": "(pts + reb)", "pa": "(pts + ast)", "ra": "(reb + ast)",
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
                   SUM(minutes) as minutes_total, COUNT(DISTINCT date) as games
            FROM {TABLE}
            WHERE opponent IS NOT NULL AND opponent != ''
            GROUP BY opponent
        """)
        rows = [dict(r) for r in c.fetchall()]

        c.execute(f"SELECT SUM({stat_sql}) as stat_total, SUM(minutes) as minutes_total FROM {TABLE}")
        league = dict(c.fetchone())
    except Exception as e:
        print(f"  ⚠️  nba_defense_ratings: couldn't compute for '{stat}' ({e})")
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
        _cache[stat] = factors
    return factors


def get_defense_factor(team_name: str, stat: str) -> float:
    """Single-team lookup. Returns 1.0 (neutral) if unavailable."""
    if not team_name:
        return 1.0
    factors = get_defense_factors(stat)
    return factors.get(team_name, 1.0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Show NBA defense-allowed ratings for a stat")
    parser.add_argument("--stat", required=True, choices=list(STAT_SQL.keys()))
    args = parser.parse_args()

    factors = get_defense_factors(args.stat)
    if not factors:
        print(f"No defense data yet for '{args.stat}' (need {MIN_GAMES_FOR_DEFENSE}+ games per team).")
    else:
        print(f"\n{args.stat.upper()} allowed vs league average (>1.0 = weak D, <1.0 = tough D)\n")
        for team, factor in sorted(factors.items(), key=lambda x: -x[1]):
            print(f"  {team:<24} {factor}")
