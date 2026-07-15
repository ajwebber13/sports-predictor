"""
wnba_player_stats.py - Culture & Pulse Analytics
Pulls WNBA player stats from ESPN box scores.
Scrapes completed games and builds per-game averages.

Usage:
  python wnba_player_stats.py backfill   # pull all 2026 games so far
  python wnba_player_stats.py update     # pull last 7 days
  python wnba_player_stats.py top        # show top players
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

WNBA_SEASON_START = "20260516"  # May 16 2026

# Commissioner's Cup dates for the 2026 season (fixed by league schedule —
# update these each season). Group-stage Cup games (Jun 1-17) already count
# toward the regular-season record, so they're tagged for reference only.
# The championship (Jun 30) does NOT count toward either team's record —
# tagging it lets hit-rate / situational queries exclude or isolate it later.
CUP_GROUP_STAGE_START = "20260601"
CUP_GROUP_STAGE_END   = "20260617"
CUP_CHAMPIONSHIP_DATE = "20260630"


def _detect_game_type(data: dict) -> str:
    """
    Best-effort tag for Commissioner's Cup games: 'cup_championship',
    'cup_group', or 'regular'.

    Primary signal: "Commissioner's Cup" text in ESPN's header/notes.
    Fallback: known 2026 Cup date range, since the exact ESPN JSON field
    for tournament games hasn't been confirmed against a live response —
    verify this against a real game_id (e.g. 401857321, the 6/30 final)
    before trusting it fully, and adjust if the text match doesn't fire.
    """
    try:
        header = data.get("header", {})
        text_blobs = []
        for comp in header.get("competitions", []):
            for note in comp.get("notes", []):
                text_blobs.append(note.get("headline", ""))
            text_blobs.append(comp.get("name", ""))
        text_blobs.append(header.get("name", ""))
        combined = " ".join(text_blobs).lower()

        game_date = ""
        comps = header.get("competitions", [])
        if comps:
            game_date = (comps[0].get("date", "") or "")[:10].replace("-", "")

        if "commissioner" in combined and "cup" in combined:
            if "championship" in combined or game_date == CUP_CHAMPIONSHIP_DATE:
                return "cup_championship"
            return "cup_group"

        if game_date == CUP_CHAMPIONSHIP_DATE:
            return "cup_championship"
        if game_date and CUP_GROUP_STAGE_START <= game_date <= CUP_GROUP_STAGE_END:
            return "cup_group"
    except Exception:
        pass
    return "regular"


def get_game_ids(date_str: str) -> list:
    """Get all completed WNBA game IDs for a given date (YYYYMMDD)."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={date_str}"
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
    Pull box score from a completed game.
    Returns list of player stat dicts.
    """
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary?event={event_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  Box score error {event_id}: {e}")
        return []

    boxscore  = data.get("boxscore", {})
    players   = boxscore.get("players", [])
    results   = []
    game_type = _detect_game_type(data)

    # Build team name list for opponent lookup
    team_names = [t.get("team", {}).get("displayName", "") for t in players]

    # Build home/away map from competitions
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
            athlete    = athlete_data.get("athlete", {})
            player_name = athlete.get("displayName", "")
            raw_stats  = athlete_data.get("stats", [])

            if not player_name or not raw_stats:
                continue

            # Parse stats by position in keys list
            def get_stat(key):
                try:
                    idx = stat_keys.index(key)
                    val = raw_stats[idx]
                    # Handle made-attempted format like "5-10"
                    if "-" in str(val) and key != "plusMinus":
                        made, att = val.split("-")
                        return float(made), float(att)
                    return float(val), 0
                except (ValueError, IndexError):
                    return 0.0, 0.0

            minutes, _  = get_stat("minutes")
            pts, _      = get_stat("points")
            reb, _      = get_stat("rebounds")
            ast, _      = get_stat("assists")
            stl, _      = get_stat("steals")
            blk, _      = get_stat("blocks")
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
                "game_type":   game_type,
            })

    return results


def save_game_stats(game_stats: list, date_str: str):
    """Save individual game stats to a temporary game log table.

    MIGRATION NOTE (2026-07): removed the inline
    CREATE TABLE IF NOT EXISTS and the ALTER TABLE ADD COLUMN loop —
    same reasoning as the other sport stat files: wnba_game_log
    already exists in schema_postgres.sql with all these columns."""
    conn = get_conn()
    c    = conn.cursor()

    saved = 0
    for p in game_stats:
        try:
            c.execute("""
                INSERT INTO wnba_game_log
                (date, player_name, team_name, minutes, pts, reb, ast,
                 stl, blk, fg_pct, three_pct, ft_pct, opponent, home_away, game_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date, player_name, team_name) DO NOTHING
            """, (
                date_str, p["player_name"], p["team_name"],
                p["minutes"], p["pts"], p["reb"], p["ast"],
                p["stl"], p["blk"], p["fg_pct"], p["three_pct"], p["ft_pct"],
                p.get("opponent", ""), p.get("home_away", ""), p.get("game_type", "regular"),
            ))
            saved += 1
        except Exception as e:
            conn.rollback()
            print(f"  Save error {p['player_name']}: {e}")

    conn.commit()
    conn.close()
    return saved


def build_player_averages():
    """
    Aggregate game log into per-game averages.
    Updates player_profiles with real WNBA stats.
    """
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
        FROM wnba_game_log
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
                "wnba", row["team_name"], row["player_name"],
                row["avg_pts"], row["avg_reb"], row["avg_ast"],
                row["avg_stl"], row["avg_blk"], row["avg_fg"],
                row["avg_3pt"], row["avg_ft"], row["avg_min"],
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
                "wnba", season, row["team_name"], row["player_name"],
                row["games"], row["avg_pts"], row["avg_reb"], row["avg_ast"],
                row["avg_stl"], row["avg_blk"], row["avg_fg"],
                row["avg_3pt"], row["avg_ft"], row["avg_min"],
                impact, "espn_boxscore"
            ))
            saved += 1

        except Exception as e:
            conn.rollback()
            print(f"  Average save error {row['player_name']}: {e}")

    conn.commit()
    conn.close()
    print(f"Player averages built: {saved} WNBA players updated")


def backfill_season(start_date: str = WNBA_SEASON_START):
    """Pull all completed WNBA games from season start to today."""
    init_player_tables()

    start  = datetime.strptime(start_date, "%Y%m%d")
    today  = datetime.now()
    total_games   = 0
    total_players = 0

    print(f"\nBackfilling WNBA box scores from {start_date} to today...")

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

    today  = datetime.now()
    total  = 0

    print(f"\nUpdating WNBA stats for last {days} days...")

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
            print_top_players("wnba", 15)
    else:
        print("Usage: python wnba_player_stats.py [backfill|update|top]")