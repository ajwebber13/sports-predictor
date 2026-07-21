"""
cfb_projections.py — Culture & Pulse Analytics
=================================================
Forward-looking prop projection, not backward-looking hit rate — same
philosophy as wnba_projections.py, mirrored directly from
nfl_projections.py (this model is fully generic across football sports;
only the table name and defense-ratings import change).

Model (per stat):
    projected_volume = avg of the stat's volume driver over recent games
    per_unit_rate     = avg (stat / volume_driver) over recent games
    projected_stat    = projected_volume * per_unit_rate
    edge              = projected_stat - line

Same per-stat volume-driver mapping as NFL (pass attempts for passing
stats, rush attempts for rushing, targets for receiving) — college
football box scores follow the same category shape, per
cfb_player_game_logs.py's module docstring caveat (unverified against
a live payload until debug_dump_keys() confirms it against a real
completed game).

Deliberately simple for v1 — no opponent/pace/injury adjustment beyond
the defense factor already built in cfb_defense_ratings.py. Same scope
as every other sport's v1: count-stat projections only, no EPA/
snap-share/target-share.
"""

import os
import sys
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn, rows_to_dicts as _rows_to_dicts

TABLE = "cfb_game_log"

VOLUME_LOOKBACK   = 5   # games used to project this week's volume (attempts/targets)
RATE_LOOKBACK      = 10  # games used to compute per-unit rate
MIN_VOLUME_GAMES   = 2   # same threshold as NFL — CFB's 12-13 game season is close enough to NFL's 17 that WNBA's higher bar doesn't apply
MIN_RATE_GAMES     = 3

STAT_CONFIG = {
    "passing_completions": ("passing_attempts", "passing_completions"),
    "passing_attempts":    ("passing_attempts", "passing_attempts"),
    "passing_yards":       ("passing_attempts", "passing_yards"),
    "passing_tds":         ("passing_attempts", "passing_tds"),
    "interceptions":       ("passing_attempts", "interceptions"),
    "rushing_attempts":    ("rushing_attempts", "rushing_attempts"),
    "rushing_yards":       ("rushing_attempts", "rushing_yards"),
    "rushing_tds":         ("rushing_attempts", "rushing_tds"),
    # CFB's ESPN receiving category has no "targets" field at all
    # (confirmed via a real backfill run — only receptions, yards,
    # yardsPerReception, TDs, longReception exist), unlike NFL where
    # targets is real and was the natural volume driver. Using
    # receptions as the volume driver instead:
    #   receiving_yards / receiving_tds: rate = per-reception average
    #   (yards-per-catch, TDs-per-catch) — a real, meaningful rate,
    #   and yards-per-reception specifically is a stat ESPN reports
    #   directly, so this isn't an invented metric.
    #   receptions itself: volume driver = receptions (self-referential
    #   by necessity, no independent driver exists) — this makes
    #   per_unit_rate trivially ~1.0, so in practice this just becomes
    #   a rolling average of recent receptions rather than a real
    #   volume*rate decomposition. That's a reasonable naive projection
    #   on its own, just not using the two-factor model meaningfully —
    #   documented here rather than left implicit.
    "receptions":          ("receptions", "receptions"),
    "receiving_yards":     ("receptions", "receiving_yards"),
    "receiving_tds":       ("receptions", "receiving_tds"),
    # "targets" deliberately NOT offered as a prop stat — CFB's ESPN
    # payload doesn't track it, so a targets prop would always come
    # back as insufficient data. Removed rather than left in to fail
    # silently every time.
}

SUPPORTED_STATS = list(STAT_CONFIG.keys())


def _recent_rows(player_name: str, lookback: int) -> list:
    """No season filter — same whole-table approach as
    cfb_defense_ratings.py. Revisit once multiple CFB seasons pile up
    in one table."""
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT date, passing_attempts, passing_completions, passing_yards, passing_tds, interceptions,
               rushing_attempts, rushing_yards, rushing_tds,
               targets, receptions, receiving_yards, receiving_tds
        FROM {TABLE}
        WHERE player_name = ?
        ORDER BY date DESC
        LIMIT ?
    """, (player_name, lookback))
    rows = _rows_to_dicts(c, c.fetchall())
    conn.close()
    return rows


def project_volume(player_name: str, volume_col: str, lookback: int = VOLUME_LOOKBACK):
    """Returns (projected_volume, games_used). None if not enough data."""
    rows = _recent_rows(player_name, lookback)
    played = [r[volume_col] for r in rows if r.get(volume_col) and r[volume_col] > 0]
    if len(played) < MIN_VOLUME_GAMES:
        return None, len(played)
    return round(sum(played) / len(played), 1), len(played)


def per_unit_rate(player_name: str, stat: str, lookback: int = RATE_LOOKBACK):
    """Returns (rate_per_unit, games_used). None if not enough data."""
    if stat not in STAT_CONFIG:
        return None, 0
    volume_col, numerator_col = STAT_CONFIG[stat]
    rows = _recent_rows(player_name, lookback)
    rates = []
    for r in rows:
        volume = r.get(volume_col)
        if not volume or volume <= 0:
            continue
        val = r.get(numerator_col)
        if val is None:
            continue
        rates.append(val / volume)
    if len(rates) < MIN_RATE_GAMES:
        return None, len(rates)
    return round(sum(rates) / len(rates), 4), len(rates)


def _tier(edge: float, line: float) -> str:
    if not line:
        return "insufficient"
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


def get_player_team(player_name: str):
    """Most recent team_name on record for this player."""
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT team_name FROM {TABLE}
        WHERE player_name = ?
        ORDER BY date DESC LIMIT 1
    """, (player_name,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def project_prop(player_name: str, stat: str, line: float, opponent_team: str = None) -> dict:
    """Core function. See nfl_projections.py's docstring for full
    parameter/return explanation — identical model here."""
    if stat not in STAT_CONFIG:
        return {"player_name": player_name, "stat": stat, "line": line, "error": f"unsupported stat '{stat}'"}

    volume_col, _ = STAT_CONFIG[stat]
    proj_volume, volume_games = project_volume(player_name, volume_col)
    raw_rate, rate_games = per_unit_rate(player_name, stat)

    if proj_volume is None or raw_rate is None:
        return {
            "player_name": player_name, "stat": stat, "line": line,
            "error": "insufficient recent data",
            "volume_sample": volume_games, "rate_sample": rate_games,
        }

    defense_factor = 1.0
    if opponent_team:
        from cfb_defense_ratings import get_defense_factor
        defense_factor = get_defense_factor(opponent_team, stat)

    adjusted_rate = round(raw_rate * defense_factor, 4)
    projected_stat = round(proj_volume * adjusted_rate, 1)
    edge = round(projected_stat - line, 1)
    edge_pct = round((edge / line) * 100, 1) if line else None
    direction = "over" if edge > 0 else ("under" if edge < 0 else "push")

    return {
        "player_name": player_name, "stat": stat, "line": line,
        "projected_volume": proj_volume, "volume_sample": volume_games,
        "volume_stat": volume_col,
        "raw_per_unit_rate": raw_rate, "rate_sample": rate_games,
        "opponent_team": opponent_team, "defense_factor": defense_factor,
        "per_unit_rate": adjusted_rate,
        "projected_stat": projected_stat,
        "edge": edge, "edge_pct": edge_pct, "direction": direction,
        "confidence_tier": _tier(edge, line),
    }


def _ensure_projection_columns():
    """Shared table across every sport — same generic column names
    every other sport's projections file already uses, no CFB-specific
    columns needed."""
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
    """Updates the existing player_props row with projection fields.
    No-ops quietly if the row doesn't exist yet or projection had an error."""
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
            projection.get("projected_volume"), projection.get("raw_per_unit_rate"),
            projection.get("per_unit_rate"), projection.get("opponent_team"),
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

    parser = argparse.ArgumentParser(description="Project a CFB player's stat vs a line")
    parser.add_argument("--player", required=True)
    parser.add_argument("--stat", required=True, choices=SUPPORTED_STATS)
    parser.add_argument("--line", required=True, type=float)
    parser.add_argument("--opponent", default=None)
    args = parser.parse_args()

    result = project_prop(args.player, args.stat, args.line, opponent_team=args.opponent)
    print(json.dumps(result, indent=2))
