"""
prop_hit_rates.py — Culture & Pulse Analytics
==============================================
Calculates player prop hit rates from sport-specific game logs with
situational filters (WNBA) or basic overall hit rate (MLB).
"""

import os
import sys
from wnba_player_categories import is_off_role
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn, rows_to_dicts as _rows_to_dicts

MIN_GAMES_OVERALL    = 5
MIN_GAMES_SITUATIONAL = 3

SUPPORTED_STATS = ["pts", "reb", "ast", "stl", "blk", "pra", "pr", "pa", "ra",
                    "hits", "runs", "rbis", "hr"]

# Per-sport table + column mapping. MLB only has 4 verified stats right now —
# total_bases/stolen_bases/pitcher props are NOT supported since
# mlb_player_stats.py doesn't capture doubles/triples/steals/pitching data.
SPORT_TABLES = {
    "wnba": "wnba_game_log",
    "mlb":  "mlb_game_log",
    "nba":  "nba_game_log",
    "nfl":  "nfl_game_log",
}

STAT_EXPR = {
    "wnba": {
        "pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
        "pra": "(pts + reb + ast)", "pr": "(pts + reb)", "pa": "(pts + ast)", "ra": "(reb + ast)",
    },
    "nba": {
        "pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
        "pra": "(pts + reb + ast)", "pr": "(pts + reb)", "pa": "(pts + ast)", "ra": "(reb + ast)",
    },
    "mlb": {
        "hits": "hits", "runs": "runs", "rbis": "rbis", "hr": "hrs",
    },
    "nfl": {
        "passing_completions": "passing_completions",
        "passing_attempts":    "passing_attempts",
        "passing_yards":       "passing_yards",
        "passing_tds":         "passing_tds",
        "interceptions":       "interceptions",
        "rushing_attempts":    "rushing_attempts",
        "rushing_yards":       "rushing_yards",
        "rushing_tds":         "rushing_tds",
        "receptions":          "receptions",
        "receiving_yards":     "receiving_yards",
        "receiving_tds":       "receiving_tds",
    },
}

MIN_GAMES_FILTER = {
    "wnba": "minutes > 0",
    "nba":  "minutes > 0",
    "mlb":  "at_bats > 0",
    "nfl":  "(passing_attempts > 0 OR rushing_attempts > 0 OR targets > 0)",
}


def _fetchone_dict(c) -> dict:
    """fetchone() equivalent of rows_to_dicts — same reason it exists:
    dict(row) / row["col"] only works when the connection's cursor
    returns dict-like row objects (true for the local SQLite fallback,
    NOT true for the Turso/libsql branch, which returns plain tuples).
    Returns {} if there's no row, so callers can safely use .get()."""
    row = c.fetchone()
    if row is None:
        return {}
    return _rows_to_dicts(c, [row])[0]


def _fetchall_dicts(c) -> list:
    return _rows_to_dicts(c, c.fetchall())


def setup_props_table():
    """MIGRATION NOTE (2026-07-14): no-op as of the Postgres migration.

    player_props already exists in schema_postgres.sql with all the
    columns this used to CREATE/ALTER in (including injury_status,
    game_home_team, game_away_team). Worth flagging: this file's own
    CREATE TABLE defined UNIQUE(date, sport, player_name, stat) — a
    DIFFERENT constraint than production's real
    UNIQUE(date, player_name, stat) (no sport column). Since
    IF NOT EXISTS meant this never actually ran against the real
    table, it never mattered — but it means the ON CONFLICT target in
    save_prop_with_hit_rates() below must match the REAL constraint,
    not this file's own (incorrect) assumption about it.

    Kept as a no-op function rather than deleted since it's called
    from save_prop_with_hit_rates() and __main__ below."""
    pass


def get_hit_rate(
    player_name: str,
    stat: str,
    line: float,
    opponent: str   = None,
    home_away: str  = None,
    is_b2b: bool    = False,
    season: str     = "2026",
    sport: str      = "wnba",
) -> dict:
    if sport not in SPORT_TABLES:
        return {"error": f"Unsupported sport: {sport}"}

    stat_map = STAT_EXPR.get(sport, {})
    if stat not in stat_map:
        return {"error": f"Unsupported stat '{stat}' for {sport}. Use one of {list(stat_map.keys())}"}

    table      = SPORT_TABLES[sport]
    row_filter = MIN_GAMES_FILTER.get(sport, "1=1")
    stat_sql   = stat_map[stat]

    conn = _get_conn()
    c    = conn.cursor()
    season_prefix = f"{season}%"

    c.execute(f"""
        SELECT COUNT(*) as games,
               SUM(CASE WHEN {stat_sql} > ? THEN 1 ELSE 0 END) as hits
        FROM {table}
        WHERE player_name = ?
          AND date LIKE ?
          AND {row_filter}
    """, (line, player_name, season_prefix))
    row = _fetchone_dict(c)
    overall_games = row.get("games") or 0
    overall_hits  = row.get("hits")  or 0
    overall_rate  = round(overall_hits / overall_games * 100, 1) if overall_games >= 1 else None

    result = {
        "overall": {"hit_rate": overall_rate, "games": overall_games, "hits": overall_hits},
        "vs_opponent": None, "home_away": None, "b2b": None,
        "confidence_tier": "insufficient", "flag": None,
    }

    if overall_games < MIN_GAMES_OVERALL:
        conn.close()
        return result

    # Situational breakdowns (opponent/home-away/B2B) only built out for WNBA —
    # MLB doesn't track opponent/home_away columns per at-bat yet.
    if sport == "wnba":
        if opponent:
            c.execute(f"""
                SELECT COUNT(*) as games,
                       SUM(CASE WHEN {stat_sql} > ? THEN 1 ELSE 0 END) as hits
                FROM {table}
                WHERE player_name = ? AND opponent = ? AND date LIKE ? AND {row_filter}
            """, (line, player_name, opponent, season_prefix))
            row = _fetchone_dict(c)
            opp_games = row.get("games") or 0
            opp_hits  = row.get("hits")  or 0
            opp_rate  = round(opp_hits / opp_games * 100, 1) if opp_games >= MIN_GAMES_SITUATIONAL else None
            result["vs_opponent"] = {"hit_rate": opp_rate, "games": opp_games, "hits": opp_hits}

        if home_away:
            c.execute(f"""
                SELECT COUNT(*) as games,
                       SUM(CASE WHEN {stat_sql} > ? THEN 1 ELSE 0 END) as hits
                FROM {table}
                WHERE player_name = ? AND home_away = ? AND date LIKE ? AND {row_filter}
            """, (line, player_name, home_away, season_prefix))
            row = _fetchone_dict(c)
            ha_games = row.get("games") or 0
            ha_hits  = row.get("hits")  or 0
            ha_rate  = round(ha_hits / ha_games * 100, 1) if ha_games >= MIN_GAMES_SITUATIONAL else None
            result["home_away"] = {"hit_rate": ha_rate, "games": ha_games, "hits": ha_hits}

        if is_b2b:
            c.execute(f"""
                SELECT date, {stat_sql} AS stat_value
                FROM {table}
                WHERE player_name = ? AND date LIKE ? AND {row_filter}
                ORDER BY date DESC LIMIT 20
            """, (player_name, season_prefix))
            rows = _fetchall_dicts(c)
            b2b_games = [(r["date"], r["stat_value"]) for r in rows if _is_b2b(r["date"], rows)]
            b2b_hits  = sum(1 for _, v in b2b_games if v > line)
            b2b_count = len(b2b_games)
            b2b_rate  = round(b2b_hits / b2b_count * 100, 1) if b2b_count >= MIN_GAMES_SITUATIONAL else None
            result["b2b"] = {"hit_rate": b2b_rate, "games": b2b_count, "hits": b2b_hits}

    result["confidence_tier"] = _confidence_tier(result, overall_rate, player_name, stat, sport)

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
    from datetime import datetime, timedelta
    try:
        d = datetime.strptime(date_str, "%Y%m%d")
        prev = (d - timedelta(days=1)).strftime("%Y%m%d")
        return any(r["date"] == prev for r in all_rows)
    except:
        return False


def _confidence_tier(result: dict, overall_rate, player_name: str = None, stat: str = None, sport: str = "wnba") -> str:
    if overall_rate is None:
        return "insufficient"

    has_flag = result.get("flag") is not None

    if overall_rate >= 65 and not has_flag:
        tier = "green"
    elif overall_rate >= 50:
        tier = "yellow"
    else:
        tier = "red"

    # Off-role downgrade only applies to WNBA (relies on wnba_player_categories.py)
    if sport == "wnba" and player_name and stat and is_off_role(player_name, stat):
        if tier == "green":
            tier = "yellow"
        elif tier == "yellow":
            tier = "red"

    return tier


def get_situational_report(player_name, stat, line, opponent, home_away, is_b2b=False, sport="wnba") -> str:
    data = get_hit_rate(player_name, stat, line, opponent, home_away, is_b2b, sport=sport)

    if "error" in data:
        return f"{player_name} — {data['error']}"

    overall = data["overall"]
    if overall["games"] < MIN_GAMES_OVERALL:
        return f"{player_name} o{line} {stat} — insufficient data ({overall['games']}G)"

    tier_emoji = {"green": "✅", "yellow": "⚠️", "red": "❌", "insufficient": "❓"}.get(data["confidence_tier"], "")
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


def save_prop_with_hit_rates(
    date: str, player_name: str, team_name: str, opponent: str, home_away: str,
    stat: str, line: float, over_odds: int = None, under_odds: int = None,
    is_b2b: bool = False, game_home_team: str = None, game_away_team: str = None,
    sport: str = "wnba",
) -> dict:
    setup_props_table()

    data = get_hit_rate(player_name, stat, line, opponent, home_away, is_b2b, sport=sport)

    overall = data.get("overall", {})
    vs_opp  = data.get("vs_opponent") or {}
    ha      = data.get("home_away")   or {}

    conn = _get_conn()
    c    = conn.cursor()
    try:
        c.execute("""
            INSERT INTO player_props
            (date, sport, player_name, team_name, opponent, home_away,
             stat, line, over_odds, under_odds,
             hit_rate_overall, hit_rate_vs_opp, hit_rate_home_away,
             games_overall, games_vs_opp, games_home_away,
             confidence_tier, captured_at, game_home_team, game_away_team)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (date, player_name, stat) DO UPDATE SET
                sport               = EXCLUDED.sport,
                team_name           = EXCLUDED.team_name,
                opponent            = EXCLUDED.opponent,
                home_away           = EXCLUDED.home_away,
                line                = EXCLUDED.line,
                over_odds           = EXCLUDED.over_odds,
                under_odds          = EXCLUDED.under_odds,
                hit_rate_overall    = EXCLUDED.hit_rate_overall,
                hit_rate_vs_opp     = EXCLUDED.hit_rate_vs_opp,
                hit_rate_home_away  = EXCLUDED.hit_rate_home_away,
                games_overall       = EXCLUDED.games_overall,
                games_vs_opp        = EXCLUDED.games_vs_opp,
                games_home_away     = EXCLUDED.games_home_away,
                confidence_tier     = EXCLUDED.confidence_tier,
                captured_at         = EXCLUDED.captured_at,
                game_home_team      = EXCLUDED.game_home_team,
                game_away_team      = EXCLUDED.game_away_team
        """, (
            date, sport, player_name, team_name, opponent, home_away,
            stat, line, over_odds, under_odds,
            overall.get("hit_rate"), vs_opp.get("hit_rate"), ha.get("hit_rate"),
            overall.get("games"), vs_opp.get("games"), ha.get("games"),
            data.get("confidence_tier"),
            datetime.now(timezone.utc).isoformat(),
            game_home_team, game_away_team,
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  Prop save error ({player_name} {stat}): {e}")
    finally:
        conn.close()

    return data


def get_strong_props(date: str = None, min_hit_rate: float = 65.0, sport: str = "wnba") -> list:
    if not date:
        from datetime import datetime, timezone, timedelta
        date = (datetime.now(timezone.utc) + timedelta(hours=-5)).strftime("%Y-%m-%d")

    conn = _get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT * FROM player_props
        WHERE date = ? AND sport = ? AND hit_rate_overall >= ?
        ORDER BY hit_rate_overall DESC
    """, (date, sport, min_hit_rate))
    rows = _fetchall_dicts(c)
    conn.close()
    return rows


if __name__ == "__main__":
    import argparse
    setup_props_table()

    parser = argparse.ArgumentParser(description="Player prop hit rate checker")
    parser.add_argument("--player", required=True)
    parser.add_argument("--stat", required=True)
    parser.add_argument("--line", required=True, type=float)
    parser.add_argument("--opponent", default=None)
    parser.add_argument("--home-away", default=None, dest="home_away")
    parser.add_argument("--b2b", action="store_true")
    parser.add_argument("--sport", default="wnba")
    args = parser.parse_args()

    report = get_situational_report(args.player, args.stat, args.line, args.opponent, args.home_away, args.b2b, sport=args.sport)
    print(f"\n{report}\n")

    data = get_hit_rate(args.player, args.stat, args.line, args.opponent, args.home_away, args.b2b, sport=args.sport)
    import json
    print(json.dumps(data, indent=2))
