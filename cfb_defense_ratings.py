"""
cfb_defense_ratings.py — Culture & Pulse Analytics
=====================================================
Computes how much of a given stat each team allows, per game, relative
to league average. Used to adjust player projections for opponent
strength — same purpose as wnba_defense_ratings.py and
nfl_defense_ratings.py, mirrored directly (this logic is fully generic
across football sports; only the table name and games threshold change).

factor > 1.0  → team allows MORE than average (weak defense — bump
                projections UP against them)
factor < 1.0  → team allows LESS than average (tough defense — bump
                projections DOWN against them)
factor = 1.0  → league average, or not enough games yet to trust a read

Normalizes by GAMES (not minutes/plays) — same reasoning as NFL:
cfb_game_log has no per-play tracking, and "yards allowed per game" is
also how real college football defensive stats are reported.

MIN_GAMES_FOR_DEFENSE set to 3, same as NFL — a 12-13 game CFB regular
season is close enough to NFL's 17 that the same threshold is
reasonable; revisit if early-season noise looks worse than NFL's did.

FBS has 130+ teams vs NFL's 32 — more teams means a real defense_factor
read takes longer to stabilize league-wide early in a season (fewer
total games per team feeding the league average at any given point),
worth keeping in mind if early-season factors look noisy.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn, rows_to_dicts as _rows_to_dicts

TABLE = "cfb_game_log"
MIN_GAMES_FOR_DEFENSE = 3

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
        rows = _rows_to_dicts(c, c.fetchall())
    except Exception as e:
        print(f"  ⚠️  defense_ratings: couldn't compute for '{stat}' ({e})")
        conn.close()
        return {}
    conn.close()

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
        # FIXED 2026-09-08: Postgres SUM() returns a Decimal, not a
        # float, for these columns — found live-testing ranking_engine.py's
        # new EFFICIENCY_STAT_MAP["cfb"] wiring: `eff_score * 0.20`
        # downstream raised TypeError mixing Decimal and float. Cast
        # before round() so this actually returns the float its own
        # signature already promised, not just for this new caller.
        factors[r["team"]] = round(float(team_rate / league_rate), 3)

    if use_cache:
        _cache[stat] = factors
    return factors


def _resolve_sp_team(mascot_name: str, sp: dict):
    """Maps a full mascot-style name (e.g. 'Ohio State Buckeyes' — the
    convention elo_ratings.team_name and cfb_game_log.opponent both
    use, and what ranking_engine.py actually passes as team_name here)
    to an entry in CFBD SP+'s own dict.

    FOUND live-testing ranking_engine.py's actual output (not just
    calling get_defense_factor directly with a short name, which
    masked this): SP+ turns out to use a THIRD naming convention, not
    matching either elo_ratings' mascot names OR cfb_data.FBS_TEAM_IDS'
    short names — confirmed live: SP+'s own keys are "Hawai'i" (with
    the apostrophe) and "Miami (OH)" (with parens), while FBS_TEAM_IDS
    has "Hawaii" and "Miami OH". An earlier version of this function
    matched mascot names against FBS_TEAM_IDS' short names (correctly)
    but then looked those short names up in `sp` verbatim — "Miami OH"
    is not a key in `sp`, only "Miami (OH)" is, so that silently fell
    through to the wrong team ("Miami" i.e. Miami FL) for Miami OH, and
    matched nothing at all for Hawaii. Now matches directly against
    SP+'s own keys instead, both sides run through the same normalizer
    already used for exactly this class of naming drift (see the
    Hawaii/Miami OH grading fix). Longest normalized key wins, so
    'Ohio State Buckeyes' can't match SP+'s 'Ohio' before its 'Ohio
    State' gets a chance."""
    from auto_results import _normalize_team_name
    normalized = _normalize_team_name(mascot_name)
    candidates = sorted(sp.keys(), key=lambda k: len(_normalize_team_name(k)), reverse=True)
    for sp_key in candidates:
        if normalized.startswith(_normalize_team_name(sp_key)):
            return sp[sp_key]
    return None


def get_defense_factor(team_name: str, stat: str) -> float:
    """Single-team lookup. Returns 1.0 (neutral) if unavailable — never
    blocks a projection just because a rating isn't ready yet.

    ENHANCED 2026-09-08: tries CFBD SP+ first, now that cfbd_api.py's
    client actually connects (see its 2026-09-08 fixes). SP+'s
    defense.rating is a real, externally-computed power rating that
    doesn't need MIN_GAMES_FOR_DEFENSE games to stabilize the way the
    raw game-log calculation below does — useful this early in a
    season. team_name here arrives in elo_ratings'/cfb_game_log's
    mascot-name convention ('Ohio State Buckeyes'), not CFBD's short
    names — see _resolve_sp_team() for that translation. Falls back to
    the raw-stat calculation if CFBD isn't configured, the team can't
    be resolved to an SP+ entry, or anything else goes wrong; must
    never raise or block a projection.

    SIGN NOTE: got this backwards on the first pass — assumed SP+'s
    defense.rating was "higher = better" from seeing Ohio State's #1
    defense paired with rating=10.1, without checking it against
    anything else. Live-tracing ranking_engine.get_rankings('cfb')'s
    actual output caught it: Ohio State (elite, real-world #1-ish
    defense) came out DEAD LAST on the efficiency component, UL Monroe
    (a real bottom-tier team) came out FIRST. Direct comparison: Ohio
    State's defense.rating is 10.1, UL Monroe's is 42.9 — SP+'s
    defense.rating is actually "LOWER = better defense" (reads like an
    expected-points-allowed cost, not a quality score), the SAME
    polarity as this function's own raw-stat return value below (>1.0
    = weak defense, <1.0 = tough) — NOT the opposite, despite looking
    that way from a single data point. ranking_engine.py's
    _get_efficiency_proxy() (the only caller) unconditionally negates
    whatever this function returns to convert that "lower = better"
    convention into its own "higher = better" one for min-max
    normalization — so def_rating is returned AS-IS here, unmodified,
    same as the raw-stat path returns its own factor as-is. Re-verified
    end-to-end through ranking_engine.get_rankings('cfb') itself after
    this fix, not just this function in isolation or a single team's
    number: Ohio State now ranks near the top of the efficiency
    component and UL Monroe near the bottom."""
    if not team_name:
        return 1.0

    try:
        from datetime import datetime
        from cfbd_api import _get_client, load_sp_ratings
        client = _get_client()
        if client:
            year = datetime.now().year if datetime.now().month >= 8 else datetime.now().year - 1
            sp = load_sp_ratings(client, year)
            rating = _resolve_sp_team(team_name, sp)
            def_rating = getattr(getattr(rating, "defense", None), "rating", None) if rating else None
            if def_rating is not None:
                return float(def_rating)
    except Exception:
        pass

    factors = get_defense_factors(stat)
    return factors.get(team_name, 1.0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Show CFB defense-allowed ratings for a stat")
    parser.add_argument("--stat", required=True, choices=list(STAT_SQL.keys()))
    args = parser.parse_args()

    factors = get_defense_factors(args.stat)
    if not factors:
        print(f"No defense data yet for '{args.stat}' (need {MIN_GAMES_FOR_DEFENSE}+ games per team).")
    else:
        print(f"\n{args.stat.upper()} allowed vs league average (>1.0 = weak D, <1.0 = tough D)\n")
        for team, factor in sorted(factors.items(), key=lambda x: -x[1]):
            print(f"  {team:<24} {factor}")
