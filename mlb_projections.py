"""
mlb_projections.py — Culture & Pulse Analytics
================================================
MLB equivalent of wnba_projections.py. Same model, at-bats instead of
minutes as the volume metric:

    projected_at_bats = avg at_bats over player's last N games
    per_ab_rate        = avg (stat / at_bats) over player's last M games
    projected_stat      = projected_at_bats * per_ab_rate (adjusted for
                           tonight's opponent via mlb_defense_ratings)
    edge                = projected_stat - line

Forward-looking, not the season-long hit rate prop_hit_rates.py already
gives you — this projects tonight specifically.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn

TABLE = "mlb_game_log"
SEASON_DEFAULT = "2026"

AB_LOOKBACK        = 5   # games used to project tonight's at-bats
RATE_LOOKBACK      = 10  # games used to compute per-at-bat rate
MIN_AB_GAMES       = 3   # need at least this many played games to trust an AB trend
MIN_RATE_GAMES     = 5   # need at least this many to trust a per-AB rate

SUPPORTED_STATS = ["hits", "runs", "rbis", "hr"]
STAT_COL = {"hits": "hits", "runs": "runs", "rbis": "rbis", "hr": "hrs"}


def _recent_rows(player_name: str, lookback: int, season: str = SEASON_DEFAULT) -> list:
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT date, at_bats, hits, runs, rbis, hrs
        FROM {TABLE}
        WHERE player_name = ? AND date LIKE ?
        ORDER BY date DESC
        LIMIT ?
    """, (player_name, f"{season}%", lookback))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def project_at_bats(player_name: str, lookback: int = AB_LOOKBACK, season: str = SEASON_DEFAULT):
    """Returns (projected_at_bats, games_used). None if not enough data."""
    rows = _recent_rows(player_name, lookback, season)
    played = [r["at_bats"] for r in rows if r.get("at_bats") and r["at_bats"] > 0]
    if len(played) < MIN_AB_GAMES:
        return None, len(played)
    return round(sum(played) / len(played), 1), len(played)


def per_ab_rate(player_name: str, stat: str, lookback: int = RATE_LOOKBACK, season: str = SEASON_DEFAULT):
    """Returns (rate_per_at_bat, games_used). None if not enough data."""
    stat_col = STAT_COL.get(stat)
    if not stat_col:
        return None, 0
    rows = _recent_rows(player_name, lookback, season)
    rates = []
    for r in rows:
        ab = r.get("at_bats")
        if not ab or ab <= 0:
            continue
        val = r.get(stat_col)
        if val is None:
            continue
        rates.append(val / ab)
    if len(rates) < MIN_RATE_GAMES:
        return None, len(rates)
    return round(sum(rates) / len(rates), 4), len(rates)


def get_player_team(player_name: str, season: str = SEASON_DEFAULT):
    """Most recent team_name on record for this player."""
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT team_name FROM {TABLE}
        WHERE player_name = ? AND date LIKE ?
        ORDER BY date DESC LIMIT 1
    """, (player_name, f"{season}%"))
    row = c.fetchone()
    conn.close()
    return row["team_name"] if row else None


def _tier(edge: float, line: float) -> str:
    if not line:
        return "insufficient"
    pct = abs(edge) / line * 100
    if pct >= 15:
        return "green"
    if pct >= 7:
        return "yellow"
    return "red"


def project_prop(player_name: str, stat: str, line: float, opponent_team: str = None, season: str = SEASON_DEFAULT) -> dict:
    """
    Core function. Same shape as wnba_projections.project_prop:
    projected_at_bats, raw/adjusted per_ab_rate, defense_factor,
    projected_stat, edge, edge_pct, direction, confidence_tier.
    Returns {"error": ...} if there isn't enough recent data.

    opponent_team: tonight's opposing pitcher's team. When given, the
    raw per-AB rate is scaled by that team's defense factor for this
    stat (from mlb_defense_ratings) before projecting.
    """
    proj_ab, ab_games = project_at_bats(player_name, season=season)
    raw_rate, rate_games = per_ab_rate(player_name, stat, season=season)

    if proj_ab is None or raw_rate is None:
        return {
            "player_name": player_name, "stat": stat, "line": line,
            "error": "insufficient recent data",
            "ab_sample": ab_games, "rate_sample": rate_games,
        }

    defense_factor = 1.0
    if opponent_team:
        from mlb_defense_ratings import get_defense_factor
        defense_factor = get_defense_factor(opponent_team, stat, season=season)

    adjusted_rate = round(raw_rate * defense_factor, 4)
    projected_stat = round(proj_ab * adjusted_rate, 2)
    edge = round(projected_stat - line, 2)
    edge_pct = round((edge / line) * 100, 1) if line else None
    direction = "over" if edge > 0 else ("under" if edge < 0 else "push")

    return {
        "player_name": player_name, "stat": stat, "line": line,
        "projected_at_bats": proj_ab, "ab_sample": ab_games,
        "raw_per_ab_rate": raw_rate, "rate_sample": rate_games,
        "opponent_team": opponent_team, "defense_factor": defense_factor,
        "per_ab_rate": adjusted_rate,
        "projected_stat": projected_stat,
        "edge": edge, "edge_pct": edge_pct, "direction": direction,
        "confidence_tier": _tier(edge, line),
    }


def _ensure_projection_columns():
    """Same player_props table WNBA projections use — MLB rows are
    distinguished by sport='mlb'. Column names are stat-agnostic
    (per_min_rate doubles as the generic 'rate' field for both sports)
    except for two MLB-specific columns added here."""
    conn = _get_conn()
    c = conn.cursor()
    for col_def in (
        "projected_at_bats REAL",
        "raw_per_ab_rate REAL",
        "per_ab_rate REAL",
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
    """Updates the existing player_props row with MLB projection fields."""
    if projection.get("error"):
        return

    _ensure_projection_columns()
    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute("""
            UPDATE player_props
            SET projected_at_bats = ?, raw_per_ab_rate = ?, per_ab_rate = ?,
                opponent_team = ?, defense_factor = ?,
                projected_stat = ?, projection_edge = ?, projection_edge_pct = ?,
                projection_direction = ?, projection_tier = ?
            WHERE date = ? AND sport = ? AND player_name = ? AND stat = ?
        """, (
            projection.get("projected_at_bats"), projection.get("raw_per_ab_rate"),
            projection.get("per_ab_rate"), projection.get("opponent_team"),
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

    parser = argparse.ArgumentParser(description="Project an MLB player's stat vs a line")
    parser.add_argument("--player", required=True)
    parser.add_argument("--stat", required=True, choices=SUPPORTED_STATS)
    parser.add_argument("--line", required=True, type=float)
    parser.add_argument("--opponent", default=None)
    parser.add_argument("--season", default=SEASON_DEFAULT)
    args = parser.parse_args()

    result = project_prop(args.player, args.stat, args.line, opponent_team=args.opponent, season=args.season)
    print(json.dumps(result, indent=2))
