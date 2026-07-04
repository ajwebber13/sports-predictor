"""
backfill_wnba_player_log.py — Culture & Pulse Analytics
========================================================
Fills the gap left by backfill_h2h_wnba.py — that script only pulls
team-level final scores into head_to_head. This script pulls PER-PLAYER
box scores (pts, reb, ast, stl, blk, minutes) for every completed WNBA
game and writes them into wnba_game_log, which prop_hit_rates.py reads
from to calculate player prop hit rates.

Without this, wnba_game_log stays near-empty and every prop shows
"insufficient data" regardless of how the season is actually going.

Usage:
  python backfill_wnba_player_log.py                 # full current season
  python backfill_wnba_player_log.py 2026-05-08       # from a specific date
  python backfill_wnba_player_log.py 2026-05-08 2026-06-30   # date range
"""

import sys
import time
import requests
from datetime import datetime, timedelta
from database import get_conn

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
SUMMARY_URL    = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"

SEASON_START_DEFAULT = "2026-05-08"  # 2026 WNBA regular season tip-off


def setup_game_log_table():
    """Create wnba_game_log if it doesn't exist, matching the columns
    prop_hit_rates.py already queries (player_name, date, opponent,
    home_away, minutes, pts, reb, ast, stl, blk)."""
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS wnba_game_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT NOT NULL,      -- YYYYMMDD, matches head_to_head style
            player_name  TEXT NOT NULL,
            team_name    TEXT NOT NULL,
            opponent     TEXT NOT NULL,
            home_away    TEXT NOT NULL,      -- 'home' or 'away'
            minutes      REAL DEFAULT 0,
            pts          REAL DEFAULT 0,
            reb          REAL DEFAULT 0,
            ast          REAL DEFAULT 0,
            stl          REAL DEFAULT 0,
            blk          REAL DEFAULT 0,
            source       TEXT DEFAULT 'espn',
            captured_at  TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, player_name)
        )
    """)

    # Migration for a wnba_game_log created before this script existed —
    # CREATE TABLE IF NOT EXISTS won't add columns to an existing table.
    try:
        c.execute("ALTER TABLE wnba_game_log ADD COLUMN source TEXT DEFAULT 'espn'")
    except Exception:
        pass  # column already exists

    try:
        c.execute("ALTER TABLE wnba_game_log ADD COLUMN captured_at TEXT")
    except Exception:
        pass  # column already exists

    conn.commit()
    conn.close()


def date_range(start: datetime, end: datetime):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def parse_minutes(min_str: str) -> float:
    """ESPN reports minutes as a string like '32' or '32:15'. Truncate seconds."""
    if not min_str:
        return 0.0
    try:
        return float(min_str.split(":")[0])
    except (ValueError, AttributeError):
        return 0.0


def get_stat(stats: list, labels: list, index: int) -> float:
    """ESPN boxscore returns a parallel 'labels' list and 'stats' value list
    per athlete — find the index of the stat we want and pull that value."""
    try:
        i = labels.index(index)
        val = stats[i]
        return float(val) if val not in ("", "--", None) else 0.0
    except (ValueError, IndexError):
        return 0.0


def fetch_completed_games_for_date(date: datetime) -> list:
    """Return list of {event_id, date} for completed games on this date."""
    date_str = date.strftime("%Y%m%d")
    try:
        r    = requests.get(SCOREBOARD_URL, params={"dates": date_str}, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception:
        return []

    games = []
    for event in data.get("events", []):
        completed = event.get("status", {}).get("type", {}).get("completed", False)
        if completed:
            games.append({"event_id": event["id"], "date": date_str})
    return games


def fetch_and_save_boxscore(event_id: str, date_str: str, conn) -> int:
    """Pull the boxscore for one game and insert every player's line
    into wnba_game_log. Returns number of player rows saved."""
    try:
        r    = requests.get(SUMMARY_URL, params={"event": event_id}, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"    boxscore fetch error ({event_id}): {e}")
        return 0

    teams = data.get("boxscore", {}).get("players", [])
    if len(teams) != 2:
        return 0

    # Figure out home/away and opponent names from the two team blocks
    team_names = [t.get("team", {}).get("displayName", "") for t in teams]

    c     = conn.cursor()
    saved = 0

    for i, team_block in enumerate(teams):
        team_name = team_names[i]
        opponent  = team_names[1 - i]

        for stat_group in team_block.get("statistics", []):
            labels = stat_group.get("labels", [])
            for athlete_entry in stat_group.get("athletes", []):
                athlete = athlete_entry.get("athlete", {})
                name    = athlete.get("displayName", "")
                stats   = athlete_entry.get("stats", [])

                if not name or not stats:
                    continue

                try:
                    min_idx = labels.index("MIN")
                    minutes = parse_minutes(stats[min_idx])
                except ValueError:
                    minutes = 0.0

                def stat_val(label):
                    try:
                        idx = labels.index(label)
                        v = stats[idx]
                        return float(v) if v not in ("", "--", None) else 0.0
                    except (ValueError, IndexError):
                        return 0.0

                pts = stat_val("PTS")
                reb = stat_val("REB")
                ast = stat_val("AST")
                stl = stat_val("STL")
                blk = stat_val("BLK")

                try:
                    c.execute("""
                        INSERT OR IGNORE INTO wnba_game_log
                        (date, player_name, team_name, opponent, home_away,
                         minutes, pts, reb, ast, stl, blk, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        date_str, name, team_name, opponent,
                        "home" if i == 0 else "away",  # ESPN lists home team's block first
                        minutes, pts, reb, ast, stl, blk, "espn_boxscore"
                    ))
                    if c.rowcount > 0:
                        saved += 1
                except Exception as e:
                    print(f"    save error ({name}): {e}")

    conn.commit()
    return saved


def backfill(start_date: str = SEASON_START_DEFAULT, end_date: str = None):
    setup_game_log_table()

    start = datetime.strptime(start_date, "%Y-%m-%d")
    end   = datetime.strptime(end_date, "%Y-%m-%d") if end_date else datetime.now()

    conn = get_conn()
    total_games   = 0
    total_players = 0

    print(f"\nBackfilling WNBA player game log: {start.date()} to {end.date()}\n")

    for date in date_range(start, end):
        games = fetch_completed_games_for_date(date)
        if not games:
            continue

        day_players = 0
        for g in games:
            saved = fetch_and_save_boxscore(g["event_id"], g["date"], conn)
            day_players += saved
            time.sleep(0.5)  # be polite to ESPN's free API

        if day_players:
            print(f"  {date.strftime('%Y-%m-%d')}: {len(games)} game(s), {day_players} player rows")
            total_games   += len(games)
            total_players += day_players

    conn.close()
    print(f"\nDone. {total_games} games processed, {total_players} player rows saved to wnba_game_log.\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) == 0:
        backfill()
    elif len(args) == 1:
        backfill(args[0])
    elif len(args) == 2:
        backfill(args[0], args[1])
    else:
        print("Usage: python backfill_wnba_player_log.py [start_date YYYY-MM-DD] [end_date YYYY-MM-DD]")
