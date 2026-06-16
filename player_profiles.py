"""
player_profiles.py - Culture & Pulse Analytics
Player profiles, stats history, and impact scores.
Supports NBA and WNBA. NFL added when season approaches.

Usage:
  python player_profiles.py nba      # backfill NBA players
  python player_profiles.py wnba     # backfill WNBA players
  python player_profiles.py update   # update current rosters
"""

import requests
import os
import time
from datetime import datetime
from database import get_conn, init_db

CURRENT_YEAR = 2026
SEASONS      = list(range(CURRENT_YEAR - 5, CURRENT_YEAR + 1))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Referer":    "https://www.espn.com/",
}


def init_player_tables():
    """Add player tables to the DB."""
    conn = get_conn()
    c    = conn.cursor()

    # Current player profiles
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_profiles (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sport           TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            player_name     TEXT NOT NULL,
            position        TEXT DEFAULT '',
            height          TEXT DEFAULT '',
            weight          TEXT DEFAULT '',
            college         TEXT DEFAULT '',
            draft_year      INTEGER DEFAULT 0,
            draft_round     INTEGER DEFAULT 0,
            draft_pick      INTEGER DEFAULT 0,
            jersey_number   TEXT DEFAULT '',
            status          TEXT DEFAULT 'active',
            pts_per_game    REAL DEFAULT 0.0,
            reb_per_game    REAL DEFAULT 0.0,
            ast_per_game    REAL DEFAULT 0.0,
            stl_per_game    REAL DEFAULT 0.0,
            blk_per_game    REAL DEFAULT 0.0,
            fg_pct          REAL DEFAULT 0.0,
            three_pct       REAL DEFAULT 0.0,
            ft_pct          REAL DEFAULT 0.0,
            minutes_per_game REAL DEFAULT 0.0,
            usage_rate      REAL DEFAULT 0.0,
            impact_score    REAL DEFAULT 0.0,
            season          TEXT DEFAULT '',
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sport, team_name, player_name, season)
        )
    """)

    # Historical stats per season
    c.execute("""
        CREATE TABLE IF NOT EXISTS player_stats_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sport           TEXT NOT NULL,
            season          TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            player_name     TEXT NOT NULL,
            position        TEXT DEFAULT '',
            games_played    INTEGER DEFAULT 0,
            pts_per_game    REAL DEFAULT 0.0,
            reb_per_game    REAL DEFAULT 0.0,
            ast_per_game    REAL DEFAULT 0.0,
            stl_per_game    REAL DEFAULT 0.0,
            blk_per_game    REAL DEFAULT 0.0,
            fg_pct          REAL DEFAULT 0.0,
            three_pct       REAL DEFAULT 0.0,
            ft_pct          REAL DEFAULT 0.0,
            minutes_per_game REAL DEFAULT 0.0,
            usage_rate      REAL DEFAULT 0.0,
            impact_score    REAL DEFAULT 0.0,
            source          TEXT DEFAULT 'espn',
            UNIQUE(sport, season, team_name, player_name)
        )
    """)

    conn.commit()
    conn.close()
    print("Player tables created: player_profiles, player_stats_history")


def calculate_impact_score(pts, reb, ast, stl, blk, usage, minutes):
    """
    Calculate player impact score 0-100.
    Weights scoring, rebounding, playmaking, defense, usage.
    """
    if minutes < 5:
        return 0.0

    score = (
        pts     * 0.35 +
        reb     * 0.15 +
        ast     * 0.15 +
        stl     * 0.10 +
        blk     * 0.10 +
        usage   * 0.15
    )
    return round(min(score, 100.0), 2)


# ── WNBA PLAYER BACKFILL ─────────────────────────────────────────────────

WNBA_TEAM_IDS = {
    "Atlanta Dream":          "20",
    "Chicago Sky":            "19",
    "Connecticut Sun":        "18",
    "Dallas Wings":           "3",
    "Golden State Valkyries": "129689",
    "Indiana Fever":          "5",
    "Las Vegas Aces":         "17",
    "Los Angeles Sparks":     "6",
    "Minnesota Lynx":         "8",
    "New York Liberty":       "9",
    "Phoenix Mercury":        "11",
    "Portland Fire":          "132052",
    "Seattle Storm":          "14",
    "Toronto Tempo":          "131935",
    "Washington Mystics":     "16",
}

NBA_TEAM_IDS = {
    "Atlanta Hawks": "1", "Boston Celtics": "2", "Brooklyn Nets": "17",
    "Charlotte Hornets": "30", "Chicago Bulls": "4", "Cleveland Cavaliers": "5",
    "Dallas Mavericks": "6", "Denver Nuggets": "7", "Detroit Pistons": "8",
    "Golden State Warriors": "9", "Houston Rockets": "10", "Indiana Pacers": "11",
    "Los Angeles Clippers": "12", "Los Angeles Lakers": "13",
    "Memphis Grizzlies": "29", "Miami Heat": "14", "Milwaukee Bucks": "15",
    "Minnesota Timberwolves": "16", "New Orleans Pelicans": "3",
    "New York Knicks": "18", "Oklahoma City Thunder": "25",
    "Orlando Magic": "19", "Philadelphia 76ers": "20", "Phoenix Suns": "21",
    "Portland Trail Blazers": "22", "Sacramento Kings": "23",
    "San Antonio Spurs": "24", "Toronto Raptors": "28",
    "Utah Jazz": "26", "Washington Wizards": "27",
}


def fetch_roster(sport: str, team_name: str, team_id: str) -> list:
    """Pull roster from ESPN for a team."""
    sport_path = "basketball/wnba" if sport == "wnba" else "basketball/nba"
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/teams/{team_id}/roster"

    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        return data.get("athletes", [])
    except Exception as e:
        print(f"  Roster fetch error {team_name}: {e}")
        return []


def parse_player(athlete: dict, team_name: str, sport: str, season: str) -> dict:
    """Extract player data from ESPN athlete object."""
    stats = {}
    for cat in athlete.get("statistics", []):
        for s in cat.get("stats", []):
            stats[s.get("name", "")] = s.get("value", 0.0)

    pts     = float(stats.get("avgPoints", stats.get("points", 0)) or 0)
    reb     = float(stats.get("avgRebounds", stats.get("rebounds", 0)) or 0)
    ast     = float(stats.get("avgAssists", stats.get("assists", 0)) or 0)
    stl     = float(stats.get("avgSteals", stats.get("steals", 0)) or 0)
    blk     = float(stats.get("avgBlocks", stats.get("blocks", 0)) or 0)
    fg_pct  = float(stats.get("fieldGoalPct", 0) or 0)
    three   = float(stats.get("threePointPct", 0) or 0)
    ft_pct  = float(stats.get("freeThrowPct", 0) or 0)
    minutes = float(stats.get("avgMinutes", 0) or 0)
    usage   = float(stats.get("usageRate", 0) or 0)
    games   = int(stats.get("gamesPlayed", 0) or 0)

    impact = calculate_impact_score(pts, reb, ast, stl, blk, usage, minutes)

    info     = athlete.get("athlete", athlete)
    position = ""
    pos_list = info.get("positions", [])
    if pos_list:
        position = pos_list[0].get("abbreviation", "")
    elif info.get("position"):
        position = info["position"].get("abbreviation", "")

    draft    = info.get("draft", {})
    college  = info.get("college", {}).get("name", "")

    return {
        "sport":            sport,
        "team_name":        team_name,
        "player_name":      info.get("displayName", info.get("fullName", "")),
        "position":         position,
        "height":           info.get("displayHeight", ""),
        "weight":           info.get("displayWeight", ""),
        "college":          college,
        "draft_year":       draft.get("year", 0),
        "draft_round":      draft.get("round", 0),
        "draft_pick":       draft.get("selection", 0),
        "jersey_number":    info.get("jersey", ""),
        "pts_per_game":     pts,
        "reb_per_game":     reb,
        "ast_per_game":     ast,
        "stl_per_game":     stl,
        "blk_per_game":     blk,
        "fg_pct":           fg_pct,
        "three_pct":        three,
        "ft_pct":           ft_pct,
        "minutes_per_game": minutes,
        "usage_rate":       usage,
        "impact_score":     impact,
        "games_played":     games,
        "season":           season,
    }


def backfill_players(sport: str):
    """Pull current rosters and stats for all teams."""
    init_player_tables()

    team_ids = WNBA_TEAM_IDS if sport == "wnba" else NBA_TEAM_IDS
    season   = str(CURRENT_YEAR) if sport == "wnba" else f"{CURRENT_YEAR-1}-{str(CURRENT_YEAR)[2:]}"

    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    print(f"\nBackfilling {sport.upper()} player profiles ({season})...")

    for team_name, team_id in team_ids.items():
        athletes = fetch_roster(sport, team_name, team_id)

        if not athletes:
            print(f"  No roster data: {team_name}")
            continue

        team_saved = 0
        for athlete in athletes:
            player = parse_player(athlete, team_name, sport, season)

            if not player["player_name"]:
                continue

            try:
                # Save to player_profiles (current)
                c.execute("""
                    INSERT OR REPLACE INTO player_profiles
                    (sport, team_name, player_name, position, height, weight,
                     college, draft_year, draft_round, draft_pick, jersey_number,
                     pts_per_game, reb_per_game, ast_per_game, stl_per_game,
                     blk_per_game, fg_pct, three_pct, ft_pct, minutes_per_game,
                     usage_rate, impact_score, season)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    player["sport"], player["team_name"], player["player_name"],
                    player["position"], player["height"], player["weight"],
                    player["college"], player["draft_year"], player["draft_round"],
                    player["draft_pick"], player["jersey_number"],
                    player["pts_per_game"], player["reb_per_game"], player["ast_per_game"],
                    player["stl_per_game"], player["blk_per_game"], player["fg_pct"],
                    player["three_pct"], player["ft_pct"], player["minutes_per_game"],
                    player["usage_rate"], player["impact_score"], player["season"],
                ))

                # Save to history
                c.execute("""
                    INSERT OR IGNORE INTO player_stats_history
                    (sport, season, team_name, player_name, position, games_played,
                     pts_per_game, reb_per_game, ast_per_game, stl_per_game,
                     blk_per_game, fg_pct, three_pct, ft_pct, minutes_per_game,
                     usage_rate, impact_score, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    player["sport"], player["season"], player["team_name"],
                    player["player_name"], player["position"], player["games_played"],
                    player["pts_per_game"], player["reb_per_game"], player["ast_per_game"],
                    player["stl_per_game"], player["blk_per_game"], player["fg_pct"],
                    player["three_pct"], player["ft_pct"], player["minutes_per_game"],
                    player["usage_rate"], player["impact_score"], "espn",
                ))
                saved += 1
                team_saved += 1

            except Exception as e:
                print(f"  Save error {player['player_name']}: {e}")

        print(f"  {team_name}: {team_saved} players loaded")
        time.sleep(0.5)

    conn.commit()
    conn.close()
    print(f"\n{sport.upper()} backfill complete: {saved} player profiles saved")


def update_rosters(sport: str):
    """
    Run after draft night or roster moves.
    Refreshes all team rosters with latest data.
    """
    print(f"\nUpdating {sport.upper()} rosters...")
    backfill_players(sport)
    print(f"{sport.upper()} rosters updated.")


def get_player_impact(player_name: str, sport: str) -> float:
    """
    Get impact score for a specific player.
    Used by injury adjustment in prediction engine.
    """
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT impact_score, pts_per_game, minutes_per_game
        FROM player_profiles
        WHERE sport = ? AND player_name = ?
        ORDER BY season DESC
        LIMIT 1
    """, (sport, player_name))

    row = c.fetchone()
    conn.close()

    if not row:
        return 5.0  # Default impact for unknown players

    return row["impact_score"]


def print_top_players(sport: str, limit: int = 10):
    """Print top players by impact score."""
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT player_name, team_name, position,
               pts_per_game, reb_per_game, ast_per_game,
               impact_score
        FROM player_profiles
        WHERE sport = ?
        ORDER BY impact_score DESC
        LIMIT ?
    """, (sport, limit))

    rows = c.fetchall()
    conn.close()

    print(f"\n{'='*60}")
    print(f"  TOP {limit} {sport.upper()} PLAYERS BY IMPACT SCORE")
    print(f"{'='*60}")
    print(f"  {'Player':<25} {'Team':<22} {'Pos':<5} {'PTS':<6} {'REB':<6} {'AST':<6} {'Impact'}")
    print(f"  {'─'*55}")
    for r in rows:
        print(f"  {r['player_name']:<25} {r['team_name']:<22} {r['position']:<5} "
              f"{r['pts_per_game']:<6.1f} {r['reb_per_game']:<6.1f} "
              f"{r['ast_per_game']:<6.1f} {r['impact_score']:.1f}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "nba":
            backfill_players("nba")
            print_top_players("nba")
        elif arg == "wnba":
            backfill_players("wnba")
            print_top_players("wnba")
        elif arg == "update":
            for sport in ["nba", "wnba"]:
                update_rosters(sport)
        elif arg == "top":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            print_top_players(sport)
    else:
        init_player_tables()
        print("Usage: python player_profiles.py [nba|wnba|update|top]")