"""
player_profile.py — Culture & Pulse Analytics
================================================
Builds the "click a player, see their story" report — Bobby's Bets'
Player Profiles feature: bio, recent game log per stat, current prop
hit rates, and a templated (not LLM) form-trend note.

Deliberately a NEW, separate file from player_profiles.py (plural),
which is the ESPN roster/impact-score BACKFILL engine — different job.
This file reads what that one (and the props pipeline) already wrote;
it doesn't fetch or backfill anything itself.

Data sources, all already populated by existing pipelines:
  - player_profiles table  -> bio (position, team, college, per-game
    averages) — NBA/WNBA only per that file's own docstring; NFL/MLB
    profiles return with bio=None, not an error, since that data
    doesn't exist yet
  - <sport>_game_log tables -> recent game-by-game values per stat
  - player_props table      -> the player's most recently captured
    hit rates per stat, i.e. "what does the market/model currently
    think of this player's active lines"

No new tables, no new data collection — purely a read/aggregate layer,
same principle as edge_finder.py.

Usage:
    py player_profile.py --player "Caitlin Clark" --sport wnba
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn, rows_to_dicts

GAME_LOG_TABLES = {"wnba": "wnba_game_log", "mlb": "mlb_game_log", "nba": "nba_game_log", "nfl": "nfl_game_log"}

# Mirrors dashboard.py's STAT_COLS exactly — kept as a local copy rather
# than importing dashboard.py, since that file pulls in streamlit as a
# module-level import and would drag a UI dependency into a pure data
# script (and this script needs to run standalone from cron/CLI).
STAT_COLS = {
    "wnba": {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
             "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")},
    "nba":  {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
             "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")},
    "mlb":  {"hits": "hits", "runs": "runs", "rbis": "rbis", "hr": "hrs"},
    "nfl":  {
        "passing_completions": "passing_completions", "passing_attempts": "passing_attempts",
        "passing_yards": "passing_yards", "passing_tds": "passing_tds", "interceptions": "interceptions",
        "rushing_attempts": "rushing_attempts", "rushing_yards": "rushing_yards", "rushing_tds": "rushing_tds",
        "receptions": "receptions", "receiving_yards": "receiving_yards", "receiving_tds": "receiving_tds",
    },
}


def get_bio(player_name: str, sport: str) -> dict:
    """Most recent season's row from player_profiles. Returns None if
    this player/sport has no bio data yet (e.g. NFL, which
    player_profiles.py's own docstring says is added later) — the
    caller decides how to degrade, this function doesn't guess."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT team_name, position, height, weight, college, jersey_number,
               pts_per_game, reb_per_game, ast_per_game, stl_per_game, blk_per_game
        FROM player_profiles
        WHERE sport = ? AND LOWER(player_name) = LOWER(?)
        ORDER BY season DESC
        LIMIT 1
    """, (sport, player_name))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return rows_to_dicts(c, [row])[0]


def get_recent_game_log(player_name: str, sport: str, n: int = 10) -> dict:
    """Returns {stat: [values oldest -> newest]} for every stat this
    sport tracks, pulled from the real game log table. Missing/None
    values are skipped rather than zero-filled, matching how the
    dashboard's sparklines already handle gaps."""
    table = GAME_LOG_TABLES.get(sport)
    stat_map = STAT_COLS.get(sport, {})
    if not table:
        return {}

    conn = get_conn()
    c = conn.cursor()
    result = {}
    for stat, col_def in stat_map.items():
        select_expr = " + ".join(col_def) if isinstance(col_def, tuple) else col_def
        c.execute(
            f"SELECT {select_expr} as val FROM {table} "
            f"WHERE LOWER(player_name) = LOWER(?) ORDER BY date DESC LIMIT ?",
            (player_name, n),
        )
        vals = [r[0] if not isinstance(r, dict) else r.get("val") for r in c.fetchall()]
        vals = [v for v in vals if v is not None]
        if vals:
            result[stat] = list(reversed(vals))  # oldest -> newest
    conn.close()
    return result


def get_current_props(player_name: str, sport: str) -> list:
    """This player's most recently captured hit rate per stat — one
    row per stat, the latest date on file, not full history. Shows
    what's currently live on their card, not a log of every past prop."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT stat, line, hit_rate_overall, games_overall, confidence_tier,
               projection_edge_pct, projection_direction, date
        FROM player_props
        WHERE sport = ? AND LOWER(player_name) = LOWER(?)
        ORDER BY date DESC
    """, (sport, player_name))
    rows = rows_to_dicts(c, c.fetchall())
    conn.close()

    seen_stats = set()
    latest = []
    for r in rows:
        if r["stat"] in seen_stats:
            continue
        seen_stats.add(r["stat"])
        latest.append(r)
    return latest


def _trend_label(recent_5: list, full: list) -> str:
    """Compares last-5-game average to the average over the full
    fetched window. Needs at least 5 games in each to say anything —
    otherwise 'steady' by default rather than a trend claim built on
    too little data."""
    if len(recent_5) < 3 or len(full) < 5:
        return "steady"
    recent_avg = sum(recent_5) / len(recent_5)
    full_avg = sum(full) / len(full)
    if full_avg == 0:
        return "steady"
    pct_diff = (recent_avg - full_avg) / full_avg * 100
    if pct_diff >= 15:
        return "trending up"
    if pct_diff <= -15:
        return "trending down"
    return "steady"


def generate_player_notes(player_name: str, sport: str, bio: dict, game_log: dict, current_props: list) -> str:
    """Templated (not LLM) summary paragraph — same principle as
    ai_prop_analyzer.py. Deterministic: same inputs always produce the
    same note."""
    parts = []

    if bio and bio.get("position"):
        team = bio.get("team_name", "")
        pos = bio.get("position", "")
        parts.append(f"{player_name} ({pos}{', ' + team if team else ''}).")

    trend_bits = []
    for stat, values in game_log.items():
        if len(values) < 3:
            continue
        recent_5 = values[-5:]
        trend = _trend_label(recent_5, values)
        if trend != "steady":
            recent_avg = round(sum(recent_5) / len(recent_5), 1)
            trend_bits.append(f"{stat.upper()} {trend} ({recent_avg} over last {len(recent_5)})")

    if trend_bits:
        parts.append("Recent form: " + ", ".join(trend_bits) + ".")
    elif game_log:
        parts.append("Production has been steady across recent games, no major trend either direction.")

    strong_props = [p for p in current_props if p.get("hit_rate_overall") and p["hit_rate_overall"] >= 65]
    if strong_props:
        best = max(strong_props, key=lambda p: p["hit_rate_overall"])
        parts.append(
            f"Currently hitting {best['hit_rate_overall']}% on the {best['stat'].upper()} "
            f"{best['line']} line over {best['games_overall']} games."
        )

    if not parts:
        return f"Not enough recent data on {player_name} yet to generate notes."

    return " ".join(parts)


def get_player_profile(player_name: str, sport: str, n_games: int = 10) -> dict:
    bio = get_bio(player_name, sport)
    game_log = get_recent_game_log(player_name, sport, n=n_games)
    current_props = get_current_props(player_name, sport)
    notes = generate_player_notes(player_name, sport, bio, game_log, current_props)
    return {
        "player_name": player_name, "sport": sport,
        "bio": bio, "game_log": game_log, "current_props": current_props, "notes": notes,
    }


def print_profile_report(player_name: str, sport: str, n_games: int = 10):
    profile = get_player_profile(player_name, sport, n_games=n_games)

    print(f"\n{'='*55}")
    print(f"  {player_name} — {sport.upper()}")
    print(f"{'='*55}\n")

    if profile["bio"]:
        b = profile["bio"]
        print(f"  {b.get('position', '?')} — {b.get('team_name', '?')}  "
              f"{b.get('height', '')} {b.get('weight', '')}  {b.get('college', '')}")
    else:
        print("  (no bio data on file for this sport yet)")

    print("\n  Recent game log (oldest -> newest):")
    if profile["game_log"]:
        for stat, values in profile["game_log"].items():
            print(f"    {stat.upper():6s} {values}")
    else:
        print("    (no game log data found)")

    print("\n  Current props:")
    if profile["current_props"]:
        for p in profile["current_props"]:
            print(f"    {p['stat'].upper():6s} {p['line']}  "
                  f"{p['hit_rate_overall']}% ({p['games_overall']}G)  as of {p['date']}")
    else:
        print("    (no current props on file)")

    print(f"\n  Notes: {profile['notes']}")
    print(f"\n{'='*55}\n")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--player", required=True)
    parser.add_argument("--sport", default="wnba", choices=["wnba", "mlb", "nba", "nfl"])
    parser.add_argument("--games", type=int, default=10)
    args = parser.parse_args()
    print_profile_report(args.player, args.sport, n_games=args.games)
