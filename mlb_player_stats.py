"""
mlb_player_stats.py - Culture & Pulse Analytics
Pulls MLB batting stats from ESPN box scores.
Scrapes completed games and builds per-game averages.
Mirrors wnba_player_stats.py pattern.

Usage:
  python mlb_player_stats.py backfill   # pull all 2026 games so far
  python mlb_player_stats.py update     # pull last 7 days
  python mlb_player_stats.py top        # show top players
"""

import requests
import time
from datetime import datetime, timedelta
from database import get_conn
from player_profiles import init_player_tables, calculate_impact_score

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

MLB_SEASON_START = "20260327"  # confirm actual 2026 Opening Day before backfilling


def get_game_ids(date_str: str) -> list:
    """Get all completed MLB game IDs for a given date (YYYYMMDD)."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard?dates={date_str}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        ids  = []
        for event in data.get("events", []):
            completed = event.get("status", {}).get("type", {}).get("completed", False)
            if completed:
                ids.append(event.get("id"))
        return ids
    except Exception as e:
        print(f"  Scoreboard error {date_str}: {e}")
        return []


def parse_box_score(event_id: str) -> list:
    """
    Pull batting box score from a completed MLB game.
    Returns list of player stat dicts.
    NOTE: stat_keys names below are best-guess based on ESPN's general
    pattern — verify against one live box score response before trusting
    fully (same caution flagged in the WNBA file for Cup game detection).
    """
    url = f"https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/summary?event={event_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  Box score error {event_id}: {e}")
        return []

    boxscore = data.get("boxscore", {})
    players  = boxscore.get("players", [])
    results  = []

    team_names = [t.get("team", {}).get("displayName", "") for t in players]

    home_away_map = {}
    for comp in data.get("header", {}).get("competitions", []):
        for competitor in comp.get("competitors", []):
            tname = competitor.get("team", {}).get("displayName", "")
            home_away_map[tname] = competitor.get("homeAway", "")

    for team_data in players:
        team_name = team_data.get("team", {}).get("displayName", "")
        opponent  = next((t for t in team_names if t != team_name), "")
        stats_list = team_data.get("statistics", [])

        # MLB box scores have separate "batting" and "pitching" stat blocks —
        # only process the batting one for this file.
        batting_block = next((s for s in stats_list if "atBats" in s.get("keys", [])), None)
        if not batting_block:
            continue

        stat_keys = batting_block.get("keys", [])
        athletes  = batting_block.get("athletes", [])

        for athlete_data in athletes:
            athlete     = athlete_data.get("athlete", {})
            player_name = athlete.get("displayName", "")
            raw_stats   = athlete_data.get("stats", [])

            if not player_name or not raw_stats:
                continue

            def get_stat(key):
                try:
                    idx = stat_keys.index(key)
                    val = raw_stats[idx]
                    return float(val) if val not in ("N/A", "-", "", None) else 0.0
                except (ValueError, IndexError):
                    return 0.0

            at_bats = get_stat("atBats")
            hits    = get_stat("hits")
            runs    = get_stat("runs")
            rbis    = get_stat("RBIs")
            hrs     = get_stat("homeRuns")
            walks   = get_stat("walks")
            avg     = round(hits / at_bats, 3) if at_bats > 0 else 0.0

            results.append({
                "player_name": player_name,
                "team_name":   team_name,
                "at_bats":     at_bats,
                "hits":        hits,
                "runs":        runs,
                "rbis":        rbis,
                "hrs":         hrs,
                "walks":       walks,
                "avg":         avg,
                "opponent":    opponent,
                "home_away":   home_away_map.get(team_name, ""),
            })

    return results


def save_game_stats(game_stats: list, date_str: str):
    """Save individual game stats to a game log table.

    MIGRATION NOTE (2026-07): removed the inline
    CREATE TABLE IF NOT EXISTS mlb_game_log that used to run here every
    call — mlb_game_log already exists in schema_postgres.sql with the
    same columns and UNIQUE constraint, so this was pure redundancy
    (and its AUTOINCREMENT syntax would have thrown a hard Postgres
    error on first run, same landmine class already removed from
    database.py's init_db())."""
    conn = get_conn()
    c    = conn.cursor()

    saved = 0
    for p in game_stats:
        try:
            c.execute("""
                INSERT INTO mlb_game_log
                (date, player_name, team_name, at_bats, hits, runs,
                 rbis, hrs, walks, avg, opponent, home_away)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date, player_name, team_name) DO NOTHING
            """, (
                date_str, p["player_name"], p["team_name"],
                p["at_bats"], p["hits"], p["runs"],
                p["rbis"], p["hrs"], p["walks"], p["avg"],
                p.get("opponent", ""), p.get("home_away", ""),
            ))
            saved += 1
        except Exception as e:
            conn.rollback()
            print(f"  Save error {p['player_name']}: {e}")

    conn.commit()
    conn.close()
    return saved


def build_player_averages():
    """Aggregate game log into per-game averages, update player_profiles."""
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT player_name, team_name,
               COUNT(*) as games,
               ROUND(AVG(at_bats)::numeric, 1) as avg_ab,
               ROUND(AVG(hits)::numeric, 1) as avg_hits,
               ROUND(AVG(runs)::numeric, 1) as avg_runs,
               ROUND(AVG(rbis)::numeric, 1) as avg_rbis,
               ROUND(AVG(hrs)::numeric, 2) as avg_hrs,
               ROUND(AVG(walks)::numeric, 1) as avg_walks,
               ROUND(AVG(avg)::numeric, 3) as season_avg
        FROM mlb_game_log
        WHERE at_bats > 0
        GROUP BY player_name, team_name
        HAVING games >= 3
    """)

    rows  = c.fetchall()
    saved = 0
    season = "2026"

    for row in rows:
        impact = calculate_impact_score(
            row["avg_rbis"], row["avg_hits"], row["avg_runs"], 0, 0, row["avg_hrs"], 0
        )

        try:
            c.execute("""
                INSERT INTO player_profiles
                (sport, team_name, player_name,
                 pts_per_game, reb_per_game, ast_per_game,
                 stl_per_game, blk_per_game, fg_pct, three_pct, ft_pct,
                 minutes_per_game, impact_score, season)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sport, team_name, player_name, season) DO UPDATE SET
                    pts_per_game     = EXCLUDED.pts_per_game,
                    reb_per_game     = EXCLUDED.reb_per_game,
                    ast_per_game     = EXCLUDED.ast_per_game,
                    stl_per_game     = EXCLUDED.stl_per_game,
                    blk_per_game     = EXCLUDED.blk_per_game,
                    fg_pct           = EXCLUDED.fg_pct,
                    three_pct        = EXCLUDED.three_pct,
                    ft_pct           = EXCLUDED.ft_pct,
                    minutes_per_game = EXCLUDED.minutes_per_game,
                    impact_score     = EXCLUDED.impact_score
            """, (
                "mlb", row["team_name"], row["player_name"],
                row["avg_rbis"], row["avg_hits"], row["avg_runs"],
                0, row["avg_hrs"], row["season_avg"],
                0, 0, 0,
                impact, season
            ))

            c.execute("""
                INSERT INTO player_stats_history
                (sport, season, team_name, player_name,
                 games_played, pts_per_game, reb_per_game, ast_per_game,
                 stl_per_game, blk_per_game, fg_pct, three_pct, ft_pct,
                 minutes_per_game, impact_score, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sport, season, team_name, player_name) DO NOTHING
            """, (
                "mlb", season, row["team_name"], row["player_name"],
                row["games"], row["avg_rbis"], row["avg_hits"], row["avg_runs"],
                0, row["avg_hrs"], row["season_avg"],
                0, 0, 0,
                impact, "espn_boxscore"
            ))
            saved += 1

        except Exception as e:
            conn.rollback()
            print(f"  Average save error {row['player_name']}: {e}")

    conn.commit()
    conn.close()
    print(f"Player averages built: {saved} MLB players updated")


def backfill_season(start_date: str = MLB_SEASON_START):
    """Pull all completed MLB games from season start to today."""
    init_player_tables()

    start = datetime.strptime(start_date, "%Y%m%d")
    today = datetime.now()
    total_games   = 0
    total_players = 0

    print(f"\nBackfilling MLB box scores from {start_date} to today...")

    current = start
    while current <= today:
        date_str = current.strftime("%Y%m%d")
        game_ids = get_game_ids(date_str)

        if game_ids:
            print(f"  {date_str}: {len(game_ids)} game(s)")
            for gid in game_ids:
                stats = parse_box_score(gid)
                if stats:
                    saved = save_game_stats(stats, date_str)
                    total_players += saved
                    total_games   += 1
                time.sleep(0.3)

        current += timedelta(days=1)

    print(f"\nBackfill complete: {total_games} games, {total_players} player-game records")
    print("Building player averages...")
    build_player_averages()


def update_recent(days: int = 7):
    """Pull last N days of games."""
    init_player_tables()

    today = datetime.now()
    total = 0

    print(f"\nUpdating MLB stats for last {days} days...")

    for i in range(days - 1, -1, -1):
        date     = today - timedelta(days=i)
        date_str = date.strftime("%Y%m%d")
        game_ids = get_game_ids(date_str)

        if game_ids:
            print(f"  {date_str}: {len(game_ids)} game(s)")
            for gid in game_ids:
                stats = parse_box_score(gid)
                if stats:
                    saved = save_game_stats(stats, date_str)
                    total += saved
                time.sleep(0.3)

    print(f"Update complete: {total} player-game records added")
    print("Rebuilding averages...")
    build_player_averages()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "backfill":
            backfill_season()
        elif arg == "update":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            update_recent(days)
        elif arg == "top":
            from player_profiles import print_top_players
            print_top_players("mlb", 15)
    else:
        print("Usage: python mlb_player_stats.py [backfill|update|top]")