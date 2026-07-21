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

# FIXED 2026-07-20: this file never called load_dotenv() — fine when
# imported by another script that already loaded the environment
# (fetch_prizepicks_props.py, render_job.py, etc.), but running this
# file directly (python mlb_projections.py --player ...) meant
# SUPABASE_DB_URL was never read from .env, so get_conn() silently
# fell back to a local SQLite file that doesn't have
# mlb_pitcher_game_log — "no such table" even though the real table
# exists in Supabase. Same bug class as several other standalone
# scripts in this repo before this fix.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn as _get_conn, rows_to_dicts as _rows_to_dicts

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
    rows = _rows_to_dicts(c, c.fetchall())
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
    return row[0] if row else None


def _tier(edge: float, line: float) -> str:
    if not line:
        return "insufficient"
    # Percent-of-line breaks down for small counting-stat lines like HITS/RBIS
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


PITCHER_TABLE = "mlb_pitcher_game_log"
PITCHER_SUPPORTED_STATS = ["strikeouts", "hits_allowed"]
PITCHER_STAT_COL = {"strikeouts": "strikeouts", "hits_allowed": "hits_allowed"}

# Pitchers only appear in the log on days they actually started/pitched
# (unlike batters, who show up most games) — a lower lookback/minimum
# than the batting AB_LOOKBACK/MIN_AB_GAMES makes sense since starts
# come roughly every 5 days, not daily.
PITCHER_LOOKBACK    = 5   # last 5 starts
MIN_PITCHER_STARTS  = 3   # need at least 3 real starts logged to trust a trend


def get_pitcher_team(player_name: str, season: str = SEASON_DEFAULT):
    """Most recent team_name on record for this PITCHER — separate
    from get_player_team() since pitchers live in a different table
    (mlb_pitcher_game_log, not mlb_game_log)."""
    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT team_name FROM {PITCHER_TABLE}
        WHERE player_name = ? AND date LIKE ?
        ORDER BY date DESC LIMIT 1
    """, (player_name, f"{season}%"))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def project_pitcher_stat(player_name: str, stat: str, lookback: int = PITCHER_LOOKBACK, season: str = SEASON_DEFAULT):
    """
    Self-referential projection — directly rolls the pitcher's own last
    N starts' totals for `stat` into an average, rather than decomposing
    into a volume-driver x rate the way batting props do (there's no
    reliable batters-faced/pitch-count volume metric captured yet).
    Same "self-referential volume driver" pattern already established
    for CFB receiving props when no separate volume stat exists.
    Works for any stat in PITCHER_STAT_COL — strikeouts, hits_allowed,
    and whatever gets added next, all share this identical math.

    Returns (projected_value, starts_used). None if fewer than
    MIN_PITCHER_STARTS real starts are on record — never guesses off
    an insufficient sample.

    NOT opponent-adjusted (no defense_factor) in this v1 — that would
    need an opponent-side batter-strikeout-rate (or contact-rate, for
    hits_allowed) signal that doesn't exist yet (mlb_defense_ratings.py
    only covers batting stats). Flagged as a real v2 enhancement, not
    silently faked as 1.0 here vs. honestly having no adjustment at all.
    """
    col = PITCHER_STAT_COL.get(stat)
    if not col:
        return None, 0

    conn = _get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT {col} FROM {PITCHER_TABLE}
        WHERE player_name = ? AND date LIKE ? AND innings_pitched > 0
        ORDER BY date DESC LIMIT ?
    """, (player_name, f"{season}%", lookback))
    rows = [r[0] for r in c.fetchall() if r[0] is not None]
    conn.close()

    if len(rows) < MIN_PITCHER_STARTS:
        return None, len(rows)

    return round(sum(rows) / len(rows), 2), len(rows)


# Backward-compatible alias — project_pitcher_strikeouts() was the
# original strikeouts-only name before this generalized to any stat.
def project_pitcher_strikeouts(player_name: str, lookback: int = PITCHER_LOOKBACK, season: str = SEASON_DEFAULT):
    return project_pitcher_stat(player_name, "strikeouts", lookback=lookback, season=season)


def project_pitcher_prop(player_name: str, stat: str, line: float, season: str = SEASON_DEFAULT) -> dict:
    """Pitcher-side counterpart to project_prop() — same output shape
    (reuses the same dict keys so save_projection()/fetch_prizepicks_props.py
    don't need stat-type-specific handling downstream), but built from
    project_pitcher_stat()'s self-referential average instead of
    the batting AB x rate decomposition. projected_at_bats/per_ab_rate
    fields are repurposed here as starts_used/projected value directly
    — same columns, different meaning, since the player_props table is
    stat-agnostic by design (see _ensure_projection_columns())."""
    if stat not in PITCHER_SUPPORTED_STATS:
        return {"player_name": player_name, "stat": stat, "line": line,
                "error": f"Unsupported pitcher stat '{stat}'"}

    projected, starts_used = project_pitcher_stat(player_name, stat, season=season)
    if projected is None:
        return {
            "player_name": player_name, "stat": stat, "line": line,
            "error": "insufficient recent data",
            "ab_sample": starts_used, "rate_sample": starts_used,
        }

    edge = round(projected - line, 2)
    edge_pct = round((edge / line) * 100, 1) if line else None
    direction = "over" if edge > 0 else ("under" if edge < 0 else "push")

    return {
        "player_name": player_name, "stat": stat, "line": line,
        "projected_at_bats": starts_used, "ab_sample": starts_used,
        "raw_per_ab_rate": None, "rate_sample": starts_used,
        "opponent_team": None, "defense_factor": 1.0,  # no matchup adj yet — see docstring
        "per_ab_rate": projected,  # repurposed: holds the projected value directly
        "projected_stat": projected,
        "edge": edge, "edge_pct": edge_pct, "direction": direction,
        "confidence_tier": _tier(edge, line),
    }


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
    if stat in PITCHER_SUPPORTED_STATS:
        return project_pitcher_prop(player_name, stat, line, season=season)

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
    parser.add_argument("--stat", required=True, choices=SUPPORTED_STATS + PITCHER_SUPPORTED_STATS)
    parser.add_argument("--line", required=True, type=float)
    parser.add_argument("--opponent", default=None)
    parser.add_argument("--season", default=SEASON_DEFAULT)
    args = parser.parse_args()

    result = project_prop(args.player, args.stat, args.line, opponent_team=args.opponent, season=args.season)
    print(json.dumps(result, indent=2))
