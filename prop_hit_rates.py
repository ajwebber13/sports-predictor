"""
prop_hit_rates.py — Culture & Pulse Analytics
==============================================
Calculates player prop hit rates from wnba_game_log with situational filters.

Situational filters:
  - vs opponent (how does this player perform against today's defense)
  - home / away split
  - back-to-back (rest days <= 1)
  - teammate out (key player missing from same team)

Also creates/maintains the player_props table for storing prop lines
when the Odds API player props endpoint becomes available.

Usage:
    from prop_hit_rates import get_hit_rate, get_situational_report
    from prop_hit_rates import setup_props_table
"""

import os
from wnba_player_categories import is_off_role
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "cp_analytics.db")

# Minimum games needed for a hit rate to be considered reliable
MIN_GAMES_OVERALL    = 5
MIN_GAMES_SITUATIONAL = 3

SUPPORTED_STATS = ["pts", "reb", "ast", "stl", "blk", "pra", "pr", "pa", "ra"]

# SQL expression per stat. Combo stats (pra/pr/pa/ra) are computed on the fly —
# wnba_game_log only stores the base columns (pts/reb/ast/stl/blk), so a combo
# prop like Points+Rebounds+Assists is graded as (pts + reb + ast) > line.
STAT_EXPR = {
    "pts": "pts",
    "reb": "reb",
    "ast": "ast",
    "stl": "stl",
    "blk": "blk",
    "pra": "(pts + reb + ast)",
    "pr":  "(pts + reb)",
    "pa":  "(pts + ast)",
    "ra":  "(reb + ast)",
}


# ─────────────────────────────────────────────
# DB SETUP
# ─────────────────────────────────────────────

def setup_props_table():
    """
    Create the player_props table if it doesn't exist.
    This is where Odds API prop lines will be stored once that feed is active.
    """
    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_props (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            sport           TEXT NOT NULL DEFAULT 'wnba',
            player_name     TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            opponent        TEXT NOT NULL,
            home_away       TEXT,
            stat            TEXT NOT NULL,         -- pts, reb, ast, stl, blk
            line            REAL NOT NULL,          -- e.g. 18.5
            over_odds       INTEGER,                -- American odds for Over
            under_odds      INTEGER,                -- American odds for Under
            hit_rate_overall   REAL,               -- % of games player hit this line
            hit_rate_vs_opp    REAL,               -- % vs this specific opponent
            hit_rate_home_away REAL,               -- % home or away (matches today)
            hit_rate_b2b       REAL,               -- % on back-to-backs (if applicable)
            games_overall      INTEGER,
            games_vs_opp       INTEGER,
            games_home_away    INTEGER,
            confidence_tier    TEXT,               -- green / yellow / red
            source          TEXT DEFAULT 'odds_api',
            captured_at     TEXT,
            UNIQUE(date, player_name, stat)
        )
    """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# CORE HIT RATE CALCULATION
# ─────────────────────────────────────────────

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_hit_rate(
    player_name: str,
    stat: str,
    line: float,
    opponent: str   = None,
    home_away: str  = None,
    is_b2b: bool    = False,
    season: str     = "2026",
) -> dict:
    """
    Calculate hit rate for a player/stat/line combo with situational breakdowns.

    Returns:
        {
          overall:      { hit_rate, games, hits },
          vs_opponent:  { hit_rate, games, hits } | None,
          home_away:    { hit_rate, games, hits } | None,
          b2b:          { hit_rate, games, hits } | None,
          confidence_tier: "green" | "yellow" | "red" | "insufficient",
          flag:         str | None   -- warning message if situational is worse than overall
        }
    """
    if stat not in SUPPORTED_STATS:
        return {"error": f"Unsupported stat: {stat}. Use one of {SUPPORTED_STATS}"}

    conn = _get_conn()
    c    = conn.cursor()

    # Filter to season (dates start with the year)
    season_prefix = f"{season}%"

    # ── Overall hit rate ──
    stat_sql = STAT_EXPR[stat]
    c.execute(f"""
        SELECT COUNT(*) as games,
               SUM(CASE WHEN {stat_sql} > ? THEN 1 ELSE 0 END) as hits
        FROM wnba_game_log
        WHERE player_name = ?
          AND date LIKE ?
          AND minutes > 0
    """, (line, player_name, season_prefix))
    row = c.fetchone()
    overall_games = row["games"] or 0
    overall_hits  = row["hits"]  or 0
    overall_rate  = round(overall_hits / overall_games * 100, 1) if overall_games >= 1 else None

    result = {
        "overall": {
            "hit_rate": overall_rate,
            "games":    overall_games,
            "hits":     overall_hits,
        },
        "vs_opponent":  None,
        "home_away":    None,
        "b2b":          None,
        "confidence_tier": "insufficient",
        "flag": None,
    }

    if overall_games < MIN_GAMES_OVERALL:
        conn.close()
        return result

    # ── vs Opponent ──
    if opponent:
        c.execute(f"""
            SELECT COUNT(*) as games,
                   SUM(CASE WHEN {stat_sql} > ? THEN 1 ELSE 0 END) as hits
            FROM wnba_game_log
            WHERE player_name = ?
              AND opponent = ?
              AND date LIKE ?
              AND minutes > 0
        """, (line, player_name, opponent, season_prefix))
        row = c.fetchone()
        opp_games = row["games"] or 0
        opp_hits  = row["hits"]  or 0
        opp_rate  = round(opp_hits / opp_games * 100, 1) if opp_games >= MIN_GAMES_SITUATIONAL else None
        result["vs_opponent"] = {
            "hit_rate": opp_rate,
            "games":    opp_games,
            "hits":     opp_hits,
        }

    # ── Home / Away ──
    if home_away:
        c.execute(f"""
            SELECT COUNT(*) as games,
                   SUM(CASE WHEN {stat_sql} > ? THEN 1 ELSE 0 END) as hits
            FROM wnba_game_log
            WHERE player_name = ?
              AND home_away = ?
              AND date LIKE ?
              AND minutes > 0
        """, (line, player_name, home_away, season_prefix))
        row = c.fetchone()
        ha_games = row["games"] or 0
        ha_hits  = row["hits"]  or 0
        ha_rate  = round(ha_hits / ha_games * 100, 1) if ha_games >= MIN_GAMES_SITUATIONAL else None
        result["home_away"] = {
            "hit_rate": ha_rate,
            "games":    ha_games,
            "hits":     ha_hits,
        }

    # ── Back-to-back ──
    if is_b2b:
        # B2B = rest_days <= 1; we approximate by checking games on consecutive dates
        # For now pull last 5 games and flag if overall trend is negative
        c.execute(f"""
            SELECT date, {stat_sql} AS stat_value
            FROM wnba_game_log
            WHERE player_name = ?
              AND date LIKE ?
              AND minutes > 0
            ORDER BY date DESC
            LIMIT 20
        """, (player_name, season_prefix))
        rows = c.fetchall()
        b2b_games = [(r["date"], r["stat_value"]) for r in rows if _is_b2b(r["date"], rows)]
        b2b_hits  = sum(1 for _, v in b2b_games if v > line)
        b2b_count = len(b2b_games)
        b2b_rate  = round(b2b_hits / b2b_count * 100, 1) if b2b_count >= MIN_GAMES_SITUATIONAL else None
        result["b2b"] = {
            "hit_rate": b2b_rate,
            "games":    b2b_count,
            "hits":     b2b_hits,
        }

    # ── Confidence tier ──
    result["confidence_tier"] = _confidence_tier(result, overall_rate, player_name, stat)

    # ── Flag if situational is significantly worse than overall ──
    flags = []
    opp_r = (result["vs_opponent"] or {}).get("hit_rate")
    ha_r  = (result["home_away"]   or {}).get("hit_rate")
    b2b_r = (result["b2b"]         or {}).get("hit_rate")

    if opp_r is not None and overall_rate and opp_r < overall_rate - 15:
        flags.append(f"struggles vs {opponent} ({opp_r}% vs {overall_rate}% overall)")
    if ha_r is not None and overall_rate and ha_r < overall_rate - 15:
        flags.append(f"worse {home_away} ({ha_r}% vs {overall_rate}% overall)")
    if b2b_r is not None and overall_rate and b2b_r < overall_rate - 15:
        flags.append(f"worse on B2Bs ({b2b_r}%)")

    result["flag"] = "; ".join(flags) if flags else None

    conn.close()
    return result


def _is_b2b(date_str: str, all_rows: list) -> bool:
    """Check if a game date is a back-to-back (previous day also has a game)."""
    from datetime import datetime, timedelta
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
        prev = (d - timedelta(days=1)).strftime("%Y%m%d")
        return any(r["date"] == prev for r in all_rows)
    except:
        return False


def _confidence_tier(
    result: dict,
    overall_rate: float | None,
    player_name: str = None,
    stat: str = None,
) -> str:
    """
    Green:  overall >= 65% and no significant situational downgrade
    Yellow: overall >= 50% or situational concern exists
    Red:    overall < 50% or significant situational flag

    Off-role downgrade: a PTS/REB/AST prop on a player whose primary
    category (scorer/rebounder/playmaker) doesn't match the stat gets
    knocked down one tier. Points is the highest-variance stat, so this
    matters most there — e.g. a playmaker's PTS line is riskier than
    their AST line even at the same hit rate. See wnba_player_categories.py.
    """
    if overall_rate is None:
        return "insufficient"

    has_flag = result.get("flag") is not None

    if overall_rate >= 65 and not has_flag:
        tier = "green"
    elif overall_rate >= 50 and not has_flag:
        tier = "yellow"
    elif overall_rate >= 50 and has_flag:
        tier = "yellow"
    else:
        tier = "red"

    if player_name and stat and is_off_role(player_name, stat):
        if tier == "green":
            tier = "yellow"
        elif tier == "yellow":
            tier = "red"

    return tier


# ─────────────────────────────────────────────
# SITUATIONAL REPORT
# ─────────────────────────────────────────────

def get_situational_report(
    player_name: str,
    stat: str,
    line: float,
    opponent: str,
    home_away: str,
    is_b2b: bool = False,
) -> str:
    """
    Returns a human-readable summary for use in the digest or Telegram alert.

    Example:
        "A'ja Wilson o18.5 pts — 72% overall (18G) | 67% vs Connecticut (3G) ✅"
    """
    data = get_hit_rate(player_name, stat, line, opponent, home_away, is_b2b)

    if "error" in data:
        return f"{player_name} — {data['error']}"

    overall = data["overall"]
    if overall["games"] < MIN_GAMES_OVERALL:
        return f"{player_name} o{line} {stat} — insufficient data ({overall['games']}G)"

    tier_emoji = {"green": "✅", "yellow": "⚠️", "red": "❌", "insufficient": "❓"}.get(
        data["confidence_tier"], ""
    )

    parts = [f"{overall['hit_rate']}% overall ({overall['games']}G)"]

    opp = data.get("vs_opponent") or {}
    if opp.get("hit_rate") is not None:
        parts.append(f"{opp['hit_rate']}% vs {opponent} ({opp['games']}G)")

    ha = data.get("home_away") or {}
    if ha.get("hit_rate") is not None:
        label = "home" if home_away == "home" else "away"
        parts.append(f"{ha['hit_rate']}% {label} ({ha['games']}G)")

    b2b = data.get("b2b") or {}
    if b2b.get("hit_rate") is not None:
        parts.append(f"{b2b['hit_rate']}% B2B ({b2b['games']}G)")

    summary = f"{player_name} o{line} {stat} — " + " | ".join(parts) + f" {tier_emoji}"

    if data.get("flag"):
        summary += f"\n    ⚠️ {data['flag']}"

    return summary


# ─────────────────────────────────────────────
# SAVE PROP LINE WITH HIT RATES
# ─────────────────────────────────────────────

def save_prop_with_hit_rates(
    date: str,
    player_name: str,
    team_name: str,
    opponent: str,
    home_away: str,
    stat: str,
    line: float,
    over_odds: int  = None,
    under_odds: int = None,
    is_b2b: bool    = False,
) -> dict:
    """
    Calculate hit rates for a prop line and save to player_props table.
    Call this when ingesting prop lines from the Odds API.
    """
    setup_props_table()

    data = get_hit_rate(player_name, stat, line, opponent, home_away, is_b2b)

    overall   = data.get("overall", {})
    vs_opp    = data.get("vs_opponent") or {}
    ha        = data.get("home_away")   or {}

    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()
    try:
        c.execute("""
            INSERT OR REPLACE INTO player_props
            (date, player_name, team_name, opponent, home_away,
             stat, line, over_odds, under_odds,
             hit_rate_overall, hit_rate_vs_opp, hit_rate_home_away,
             games_overall, games_vs_opp, games_home_away,
             confidence_tier, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            date, player_name, team_name, opponent, home_away,
            stat, line, over_odds, under_odds,
            overall.get("hit_rate"), vs_opp.get("hit_rate"), ha.get("hit_rate"),
            overall.get("games"), vs_opp.get("games"), ha.get("games"),
            data.get("confidence_tier"),
            datetime.now(timezone.utc).isoformat(),
        ))
        conn.commit()
    except Exception as e:
        print(f"  Prop save error ({player_name} {stat}): {e}")
    finally:
        conn.close()

    return data


# ─────────────────────────────────────────────
# QUICK LOOKUP — TODAY'S STRONG PROPS
# ─────────────────────────────────────────────

def get_strong_props(date: str = None, min_hit_rate: float = 65.0) -> list:
    """
    Return saved props from player_props with hit_rate_overall >= threshold.
    Used by the digest to surface strong prop signals.
    """
    if not date:
        from datetime import datetime, timezone, timedelta
        date = (datetime.now(timezone.utc) + timedelta(hours=-5)).strftime("%Y-%m-%d")

    conn = _get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT *
        FROM player_props
        WHERE date = ?
          AND hit_rate_overall >= ?
        ORDER BY hit_rate_overall DESC
    """, (date, min_hit_rate))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ─────────────────────────────────────────────
# CLI — test a player on the command line
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    setup_props_table()

    parser = argparse.ArgumentParser(description="Player prop hit rate checker")
    parser.add_argument("--player",   required=True,  help="Player name")
    parser.add_argument("--stat",     required=True,  help="pts / reb / ast / stl / blk")
    parser.add_argument("--line",     required=True,  type=float, help="Prop line (e.g. 18.5)")
    parser.add_argument("--opponent", default=None,   help="Today's opponent team name")
    parser.add_argument("--home-away", default=None,  dest="home_away", help="home or away")
    parser.add_argument("--b2b",      action="store_true", help="Is this a back-to-back?")
    args = parser.parse_args()

    report = get_situational_report(
        args.player, args.stat, args.line,
        args.opponent, args.home_away, args.b2b
    )
    print(f"\n{report}\n")

    # Full breakdown
    data = get_hit_rate(
        args.player, args.stat, args.line,
        args.opponent, args.home_away, args.b2b
    )
    import json
    print(json.dumps(data, indent=2))
