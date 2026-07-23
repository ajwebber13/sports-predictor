"""
mlb_defense_ratings.py — Culture & Pulse Analytics
====================================================
MLB equivalent of wnba_defense_ratings.py. Computes how much of a given
stat each team allows, per at-bat faced, relative to league average.

Uses mlb_game_log's own "opponent" column — no backfill needed, this
reads off the same season-to-date data that's already being written by
mlb_player_stats.py every game day.

factor > 1.0  → team allows MORE than average (weak pitching/defense —
                bump projections UP against them)
factor < 1.0  → team allows LESS than average (tough pitching/defense —
                bump projections DOWN against them)
factor = 1.0  → league average, or not enough games yet to trust a read
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn, rows_to_dicts as _rows_to_dicts

TABLE = "mlb_game_log"
SEASON_DEFAULT = "2026"
MIN_GAMES_FOR_DEFENSE = 5  # games faced (as the opponent) before trusting a read

_cache = {}  # {(stat, season): {team_name: factor}}

# Matches prop_hit_rates.py's MLB stat set — hrs is the column name, hr is the prop stat key
STAT_COL = {
    "hits": "hits", "runs": "runs", "rbis": "rbis", "hr": "hrs",
}

# Pitching stats live in a separate table (mlb_pitcher_game_log) and need
# a different rate denominator — ESPN's box score doesn't expose a real
# "batters faced" column, so innings_pitched is used as the closest proxy.
# "opponent" in mlb_pitcher_game_log is the BATTING team a pitcher faced
# that game, so grouping by opponent here gives each team's strikeout
# rate taken against opposing pitching — exactly what a strikeout prop's
# defense factor needs (a team that strikes out MORE = weak "defense" =
# favorable for an Over on pitcher strikeouts).
PITCHER_STAT_COL = {
    "strikeouts": "strikeouts", "hits_allowed": "hits_allowed",
}
PITCHER_TABLE = "mlb_pitcher_game_log"
PITCHER_RATE_DENOM_COL = "innings_pitched"

def get_defense_factors(stat: str, season: str = SEASON_DEFAULT, use_cache: bool = True) -> dict:
    """Returns {team_name: factor} for every team with enough games faced."""
    is_pitcher_stat = stat in PITCHER_STAT_COL
    stat_col       = PITCHER_STAT_COL.get(stat) if is_pitcher_stat else STAT_COL.get(stat)
    table          = PITCHER_TABLE if is_pitcher_stat else TABLE
    rate_denom_col = PITCHER_RATE_DENOM_COL if is_pitcher_stat else "at_bats"
    if not stat_col:
        return {}

    cache_key = (stat, season)
    if use_cache and cache_key in _cache:
        return _cache[cache_key]

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute(f"""
            SELECT opponent as team, SUM({stat_col}) as stat_total,
                   SUM({rate_denom_col}) as denom_total, COUNT(DISTINCT date) as games
            FROM {table}
            WHERE date LIKE ? AND opponent IS NOT NULL AND opponent != ''
            GROUP BY opponent
        """, (f"{season}%",))
        rows = _rows_to_dicts(c, c.fetchall())

        c.execute(f"""
            SELECT SUM({stat_col}) as stat_total, SUM({rate_denom_col}) as denom_total
            FROM {table}
            WHERE date LIKE ?
        """, (f"{season}%",))
        league_row = c.fetchone()
        league_rows = _rows_to_dicts(c, [league_row]) if league_row else []
        league = league_rows[0] if league_rows else {}
    except Exception as e:
        print(f"  ⚠️  mlb_defense_ratings: couldn't compute for '{stat}' ({e})")
        conn.close()
        return {}
    conn.close()

    league_denom = league.get("denom_total") or 0
    league_stat  = league.get("stat_total") or 0
    if league_denom <= 0 or league_stat <= 0:
        return {}
    league_rate = league_stat / league_denom

    factors = {}
    for r in rows:
        if (r["games"] or 0) < MIN_GAMES_FOR_DEFENSE or not r["denom_total"]:
            continue
        team_rate = r["stat_total"] / r["denom_total"]
        factors[r["team"]] = round(team_rate / league_rate, 3)

    if use_cache:
        _cache[cache_key] = factors
    return factors


def get_defense_factor(team_name: str, stat: str, season: str = SEASON_DEFAULT) -> float:
    """Single-team lookup. Returns 1.0 (neutral) if unavailable."""
    if not team_name:
        return 1.0
    factors = get_defense_factors(stat, season=season)
    return factors.get(team_name, 1.0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Show MLB defense-allowed ratings for a stat")
    parser.add_argument("--stat", required=True, choices=list(STAT_COL.keys()) + list(PITCHER_STAT_COL.keys()))
    parser.add_argument("--season", default=SEASON_DEFAULT)
    args = parser.parse_args()

    factors = get_defense_factors(args.stat, season=args.season)
    if not factors:
        print(f"No defense data yet for '{args.stat}' (need {MIN_GAMES_FOR_DEFENSE}+ games faced per team).")
    else:
        print(f"\n{args.stat.upper()} allowed vs league average (>1.0 = weak, <1.0 = tough)\n")
        for team, factor in sorted(factors.items(), key=lambda x: -x[1]):
            print(f"  {team:<24} {factor}")
