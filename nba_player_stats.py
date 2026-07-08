"""
nba_player_stats.py - Culture & Pulse Analytics
Pulls NBA player stats from ESPN box scores.
Scrapes completed games and builds per-game averages.

Mirrors wnba_player_stats.py exactly (same ESPN API shape, same table
layout) — swap "basketball/wnba" for "basketball/nba" and that's the
whole diff.

NOTE: the NBA is in its offseason as of this build (2025-26 season
ended in June 2026, next season tips off ~October 2026). This backfill
pulls the completed 2025-26 season for historical data — star player
rankings, defense ratings, and projections built off this will be
ready to go the moment real games resume, but there's nothing live to
alert on until then.

Usage:
  python nba_player_stats.py backfill   # pull all 2025-26 season games
  python nba_player_stats.py update     # pull last 7 days (no-op in offseason)
  python nba_player_stats.py top        # show top players
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

# 2025-26 NBA regular season opened Oct 21, 2025. Backfill runs through
# today, which naturally covers the playoffs/Finals too since those
# games show up as completed on ESPN's scoreboard the same way.
NBA_SEASON_START = "20251021"


def get_game_ids(date_str: str) -> list:
    """Get all completed NBA game IDs for a given date (YYYYMMDD)."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={date_str}"
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
    """Pull box score from a completed game. Returns list of player stat dicts."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}"
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

        if not stats_list:
            continue

        stat_keys = stats_list[0].get("keys", [])
        athletes  = stats_list[0].get("athletes", [])

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
                    if "-" in str(val) and key != "plusMinus":
                        made, att = val.split("-")
                        return float(made), float(att)
                    return float(val), 0
                except (ValueError, IndexError):
                    return 0.0, 0.0

            minutes, _ = get_stat("minutes")
            pts, _     = get_stat("points")
            reb, _     = get_stat("rebounds")
            ast, _     = get_stat("assists")
            stl, _     = get_stat("steals")
            blk, _     = get_stat("blocks")
            fg_made, fg_att = get_stat("fieldGoalsMade-fieldGoalsAttempted")
            three_made, three_att = get_stat("threePointFieldGoalsMade-threePointFieldGoalsAttempted")
            ft_made, ft_att = get_stat("freeThrowsMade-freeThrowsAttempted")

            fg_pct    = round(fg_made / fg_att, 3) if fg_att > 0 else 0.0
            three_pct = round(three_made / three_att, 3) if three_att > 0 else 0.0
            ft_pct    = round(ft_made / ft_att, 3) if ft_att > 0 else 0.0

            results.append({
                "player_name": player_name,
                "team_name":   team_name,
                "minutes":     minutes,
                "pts":         pts,
                "reb":         reb,
                "ast":         ast,
                "stl":         stl,
                "blk":         blk,
                "fg_pct":      fg_pct,
                "three_pct":   three_pct,
                "ft_pct":      ft_pct,
                "opponent":    opponent,
                "home_away":   home_away_map.get(team_name, ""),
            })

    return results


def save_game_stats(game_stats: list, date_str: str):
    """Save individual game stats to nba_game_log."""
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS nba_game_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT NOT NULL,
            player_name TEXT NOT NULL,
            team_name   TEXT NOT NULL,
            minutes     REAL DEFAULT 0,
            pts         REAL DEFAULT 0,
            reb         REAL DEFAULT 0,
            ast         REAL DEFAULT 0,
            stl         REAL DEFAULT 0,
            blk         REAL DEFAULT 0,
            fg_pct      REAL DEFAULT 0,
            three_pct   REAL DEFAULT 0,
            ft_pct      REAL DEFAULT 0,
            opponent    TEXT DEFAULT '',
            home_away   TEXT DEFAULT '',
            UNIQUE(date, player_name, team_name)
        )
    """)

    saved = 0
    for p in game_stats:
        try:
            c.execute("""
                INSERT OR IGNORE INTO nba_game_log
                (date, player_name, team_name, minutes, pts, reb, ast,
                 stl, blk, fg_pct, three_pct, ft_pct, opponent, home_away)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str, p["player_name"], p["team_name"],
                p["minutes"], p["pts"], p["reb"], p["ast"],
                p["stl"], p["blk"], p["fg_pct"], p["three_pct"], p["ft_pct"],
                p.get("opponent", ""), p.get("home_away", ""),
            ))
            saved += 1
        except Exception as e:
            print(f"  Save error {p['player_name']}: {e}")

    conn.commit()
    conn.close()
    return saved


def build_player_averages():
    """Aggregate game log into per-game averages, same as WNBA's version."""
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT player_name, team_name,
               COUNT(*) as games,
               ROUND(AVG(minutes), 1) as avg_min,
               ROUND(AVG(pts), 1) as avg_pts,
               ROUND(AVG(reb), 1) as avg_reb,
               ROUND(AVG(ast), 1) as avg_ast,
               ROUND(AVG(stl), 1) as avg_stl,
               ROUND(AVG(blk), 1) as avg_blk,
               ROUND(AVG(fg_pct), 3) as avg_fg,
               ROUND(AVG(three_pct), 3) as avg_3pt,
               ROUND(AVG(ft_pct), 3) as avg_ft
        FROM nba_game_log
        WHERE minutes > 0
        GROUP BY player_name, team_name
        HAVING games >= 3
    """)

    rows  = c.fetchall()
    saved = 0
    season = "2026"

    for row in rows:
        impact = calculate_impact_score(
            row["avg_pts"], row["avg_reb"], row["avg_ast"],
            row["avg_stl"], row["avg_blk"], 0, row["avg_min"]
        )

        try:
            c.execute("""
                INSERT OR REPLACE INTO player_profiles
                (sport, team_name, player_name,
                 pts_per_game, reb_per_game, ast_per_game,
                 stl_per_game, blk_per_game, fg_pct, three_pct, ft_pct,
                 minutes_per_game, impact_score, season)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "nba", row["team_name"], row["player_name"],
                row["avg_pts"], row["avg_reb"], row["avg_ast"],
                row["avg_stl"], row["avg_blk"], row["avg_fg"],
                row["avg_3pt"], row["avg_ft"], row["avg_min"],
                impact, season
            ))

            c.execute("""
                INSERT OR IGNORE INTO player_stats_history
                (sport, season, team_name, player_name,
                 games_played, pts_per_game, reb_per_game, ast_per_game,
                 stl_per_game, blk_per_game, fg_pct, three_pct, ft_pct,
                 minutes_per_game, impact_score, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "nba", season, row["team_name"], row["player_name"],
                row["games"], row["avg_pts"], row["avg_reb"], row["avg_ast"],
                row["avg_stl"], row["avg_blk"], row["avg_fg"],
                row["avg_3pt"], row["avg_ft"], row["avg_min"],
                impact, "espn_boxscore"
            ))
            saved += 1

        except Exception as e:
            print(f"  Average save error {row['player_name']}: {e}")

    conn.commit()
    conn.close()
    print(f"Player averages built: {saved} NBA players updated")


def backfill_season(start_date: str = NBA_SEASON_START):
    """Pull all completed NBA games from season start to today."""
    init_player_tables()

    start  = datetime.strptime(start_date, "%Y%m%d")
    today  = datetime.now()
    total_games   = 0
    total_players = 0

    print(f"\nBackfilling NBA box scores from {start_date} to today...")
    print("(NBA is in its offseason — this pulls the completed 2025-26 season for historical data)\n")

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
    """Pull last N days of games. Will be a no-op until the new season starts."""
    init_player_tables()

    today  = datetime.now()
    total  = 0

    print(f"\nUpdating NBA stats for last {days} days...")

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
            print_top_players("nba", 15)
    else:
        print("Usage: python nba_player_stats.py [backfill|update|top]")
