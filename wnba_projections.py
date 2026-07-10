"""
wnba_projections.py — Culture & Pulse Analytics
=================================================
Forward-looking prop projection, not backward-looking hit rate.

Model:
    projected_minutes  = avg minutes over player's last N games
    per_min_rate        = avg (stat / minutes) over player's last M games
    projected_stat       = projected_minutes * per_min_rate
    edge                 = projected_stat - line

This is the "clean and manageable" version: two numbers (minutes trend,
per-minute rate) instead of a season-long hit-rate percentage that
doesn't move with role changes, blowouts, or rest.

Deliberately simple for v1 — no opponent/pace/injury adjustment yet.
Those are natural next upgrades, not required to be useful today.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn, rows_to_dicts as _rows_to_dicts

TABLE = "wnba_game_log"
SEASON_DEFAULT = "2026"

MINUTES_LOOKBACK       = 5   # games used to project tonight's minutes
RATE_LOOKBACK          = 10  # games used to compute per-minute rate
MIN_MINUTES_GAMES      = 3   # need at least this many played games to trust a minutes trend
MIN_RATE_GAMES         = 5   # need at least this many to trust a per-minute rate

SUPPORTED_STATS = ["pts", "reb", "ast", "stl", "blk", "pra", "pr", "pa", "ra"]


def _recent_rows(player_name: str, lookback: int, season: str = SEASON_DEFAULT) -> list:
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT date, minutes, pts, reb, ast, stl, blk
        FROM {TABLE}
        WHERE player_name = ? AND date LIKE ?
        ORDER BY date DESC
        LIMIT ?
    """, (player_name, f"{season}%", lookback))
    rows = _rows_to_dicts(c, c.fetchall())
    conn.close()
    return rows


def _stat_value(row: dict, stat: str):
    pts, reb, ast, stl, blk = row.get("pts") or 0, row.get("reb") or 0, row.get("ast") or 0, row.get("stl") or 0, row.get("blk") or 0
    return {
        "pts": pts, "reb": reb, "ast": ast, "stl": stl, "blk": blk,
        "pra": pts + reb + ast, "pr": pts + reb, "pa": pts + ast, "ra": reb + ast,
    }.get(stat)


def project_minutes(player_name: str, lookback: int = MINUTES_LOOKBACK, season: str = SEASON_DEFAULT):
    """Returns (projected_minutes, games_used). None if not enough data."""
    rows = _recent_rows(player_name, lookback, season)
    played = [r["minutes"] for r in rows if r.get("minutes") and r["minutes"] > 0]
    if len(played) < MIN_MINUTES_GAMES:
        return None, len(played)
    return round(sum(played) / len(played), 1), len(played)


def per_minute_rate(player_name: str, stat: str, lookback: int = RATE_LOOKBACK, season: str = SEASON_DEFAULT):
    """Returns (rate_per_minute, games_used). None if not enough data."""
    if stat not in SUPPORTED_STATS:
        return None, 0
    rows = _recent_rows(player_name, lookback, season)
    rates = []
    for r in rows:
        minutes = r.get("minutes")
        if not minutes or minutes <= 0:
            continue
        val = _stat_value(r, stat)
        if val is None:
            continue
        rates.append(val / minutes)
    if len(rates) < MIN_RATE_GAMES:
        return None, len(rates)
    return round(sum(rates) / len(rates), 4), len(rates)


def _tier(edge: float, line: float) -> str:
    if not line:
        return "insufficient"
    # Percent-of-line breaks down for small counting-stat lines like STL/BLK
    # at 0.5-1.5 — dividing by a near-zero line inflates trivial differences
    # into huge percentages (a 0.42-vs-0.5 projection showing "-16% edge, GREEN"
    # is noise, not a real signal). Below this line value, judge the edge in
    # raw units instead of percentage.
    LOW_LINE_THRESHOLD = 3.0
    if line < LOW_LINE_THRESHOLD:
        abs_edge = abs(edge)
        if abs_edge >= 0.5:
            return "green"
        if abs_edge >= 0.25:
            return "yellow"
        return "red"
    pct = abs(edge) / line * 100
    if pct >= 15:
        return "green"
    if pct >= 7:
        return "yellow"
    return "red"


def get_player_team(player_name: str, season: str = SEASON_DEFAULT):
    """Most recent team_name on record for this player. Used to figure
    out who tonight's opponent actually is from the game's home/away teams."""
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT team_name FROM {TABLE}
        WHERE player_name = ? AND date LIKE ?
        ORDER BY date DESC LIMIT 1
    """, (player_name, f"{season}%"))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def project_prop(player_name: str, stat: str, line: float, opponent_team: str = None, season: str = SEASON_DEFAULT) -> dict:
    """
    Core function. Returns a dict with projected_minutes, raw/adjusted
    per_min_rate, defense_factor, projected_stat, edge, edge_pct,
    direction (over/under), confidence_tier.
    Returns {"error": ...} if there isn't enough recent data to trust a projection.

    opponent_team: tonight's opponent, if known. When given, the raw
    per-minute rate is scaled by that team's defense factor for this
    stat before projecting — a weak defense bumps the projection up,
    a tough one bumps it down. Falls back to no adjustment (factor 1.0)
    if the opponent isn't known or doesn't have enough games yet.
    """
    proj_min, min_games = project_minutes(player_name, season=season)
    raw_rate, rate_games = per_minute_rate(player_name, stat, season=season)

    if proj_min is None or raw_rate is None:
        return {
            "player_name": player_name, "stat": stat, "line": line,
            "error": "insufficient recent data",
            "minutes_sample": min_games, "rate_sample": rate_games,
        }

    defense_factor = 1.0
    if opponent_team:
        from wnba_defense_ratings import get_defense_factor
        defense_factor = get_defense_factor(opponent_team, stat, season=season)

    adjusted_rate = round(raw_rate * defense_factor, 4)
    projected_stat = round(proj_min * adjusted_rate, 1)
    edge = round(projected_stat - line, 1)
    edge_pct = round((edge / line) * 100, 1) if line else None
    direction = "over" if edge > 0 else ("under" if edge < 0 else "push")

    return {
        "player_name": player_name, "stat": stat, "line": line,
        "projected_minutes": proj_min, "minutes_sample": min_games,
        "raw_per_min_rate": raw_rate, "rate_sample": rate_games,
        "opponent_team": opponent_team, "defense_factor": defense_factor,
        "per_min_rate": adjusted_rate,
        "projected_stat": projected_stat,
        "edge": edge, "edge_pct": edge_pct, "direction": direction,
        "confidence_tier": _tier(edge, line),
    }


def _ensure_projection_columns():
    """Adds projection columns to player_props if they don't exist yet."""
    conn = _get_conn()
    c = conn.cursor()
    for col_def in (
        "projected_minutes REAL",
        "raw_per_min_rate REAL",
        "per_min_rate REAL",
        "opponent_team TEXT",
        "defense_factor REAL",
        "projected_stat REAL",
        "projection_edge REAL",
        "projection_edge_pct REAL",
        "projection_direction TEXT",
        "projection_tier TEXT",
    ):
        try:
            c.execute(f"ALTER TABLE player_props ADD COLUMN {col_def}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def save_projection(date: str, sport: str, player_name: str, stat: str, projection: dict):
    """
    Updates the existing player_props row (already written by
    save_prop_with_hit_rates) with projection fields.
    No-ops quietly if the row doesn't exist yet or projection had an error.
    """
    if projection.get("error"):
        return

    _ensure_projection_columns()
    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute("""
            UPDATE player_props
            SET projected_minutes = ?, raw_per_min_rate = ?, per_min_rate = ?,
                opponent_team = ?, defense_factor = ?,
                projected_stat = ?, projection_edge = ?, projection_edge_pct = ?,
                projection_direction = ?, projection_tier = ?
            WHERE date = ? AND sport = ? AND player_name = ? AND stat = ?
        """, (
            projection.get("projected_minutes"), projection.get("raw_per_min_rate"),
            projection.get("per_min_rate"), projection.get("opponent_team"),
            projection.get("defense_factor"), projection.get("projected_stat"),
            projection.get("edge"), projection.get("edge_pct"),
            projection.get("direction"), projection.get("confidence_tier"),
            date, sport, player_name, stat,
        ))
        conn.commit()
    except Exception as e:
        print(f"  Projection save error ({player_name} {stat}): {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Project a WNBA player's stat vs a line")
    parser.add_argument("--player", required=True)
    parser.add_argument("--stat", required=True, choices=SUPPORTED_STATS)
    parser.add_argument("--line", required=True, type=float)
    parser.add_argument("--season", default=SEASON_DEFAULT)
    args = parser.parse_args()

    result = project_prop(args.player, args.stat, args.line, season=args.season)
    print(json.dumps(result, indent=2))
