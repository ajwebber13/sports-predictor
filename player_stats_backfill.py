"""
player_stats_backfill.py - Culture & Pulse Analytics
Pulls player stats for NBA and NFL using working data sources.
NBA: nba_api
NFL: nfl-data-py

Usage:
  python player_stats_backfill.py nba
  python player_stats_backfill.py nfl
  python player_stats_backfill.py all
"""

import os
import time
from datetime import datetime
from database import get_conn, init_db
from player_profiles import (
    init_player_tables,
    calculate_impact_score,
    NBA_TEAM_IDS,
)

CURRENT_YEAR = 2026


def backfill_nba_stats():
    """Pull NBA player stats using nba_api for last 5 seasons."""
    init_player_tables()

    try:
        from nba_api.stats.endpoints import leaguedashplayerstats
    except ImportError:
        print("nba_api not installed. Run: pip install nba_api")
        return

    # NBA team abbreviation to full name map
    NBA_ABBREV = {
        "ATL": "Atlanta Hawks", "BOS": "Boston Celtics",
        "BKN": "Brooklyn Nets", "CHA": "Charlotte Hornets",
        "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
        "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets",
        "DET": "Detroit Pistons", "GSW": "Golden State Warriors",
        "HOU": "Houston Rockets", "IND": "Indiana Pacers",
        "LAC": "Los Angeles Clippers", "LAL": "Los Angeles Lakers",
        "MEM": "Memphis Grizzlies", "MIA": "Miami Heat",
        "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
        "NOP": "New Orleans Pelicans", "NYK": "New York Knicks",
        "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic",
        "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
        "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
        "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors",
        "UTA": "Utah Jazz", "WAS": "Washington Wizards",
    }

    seasons = [
        "2020-21", "2021-22", "2022-23",
        "2023-24", "2024-25",
    ]

    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    for season in seasons:
        print(f"\n  NBA {season}...")
        try:
            stats = leaguedashplayerstats.LeagueDashPlayerStats(
                season=season,
                per_mode_detailed="PerGame",
                timeout=30,
            )
            df = stats.get_data_frames()[0]
            print(f"  {len(df)} players found")

            for _, row in df.iterrows():
                player_name = row.get("PLAYER_NAME", "")
                team_abbrev = row.get("TEAM_ABBREVIATION", "")
                team_name   = NBA_ABBREV.get(team_abbrev, team_abbrev)

                pts     = float(row.get("PTS", 0) or 0)
                reb     = float(row.get("REB", 0) or 0)
                ast     = float(row.get("AST", 0) or 0)
                stl     = float(row.get("STL", 0) or 0)
                blk     = float(row.get("BLK", 0) or 0)
                minutes = float(row.get("MIN", 0) or 0)
                gp      = int(row.get("GP", 0) or 0)
                fg_pct  = float(row.get("FG_PCT", 0) or 0)
                fg3_pct = float(row.get("FG3_PCT", 0) or 0)
                ft_pct  = float(row.get("FT_PCT", 0) or 0)
                usage   = float(row.get("USG_PCT", 0) or 0) * 100

                impact = calculate_impact_score(
                    pts, reb, ast, stl, blk, usage, minutes
                )

                try:
                    c.execute("""
                        INSERT OR REPLACE INTO player_stats_history
                        (sport, season, team_name, player_name, position,
                         games_played, pts_per_game, reb_per_game, ast_per_game,
                         stl_per_game, blk_per_game, fg_pct, three_pct, ft_pct,
                         minutes_per_game, usage_rate, impact_score, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        "nba", season, team_name, player_name, "",
                        gp, pts, reb, ast, stl, blk,
                        fg_pct, fg3_pct, ft_pct,
                        minutes, usage, impact, "nba_api"
                    ))

                    # Update current profile if this is latest season
                    if season == "2024-25":
                        c.execute("""
                            INSERT OR REPLACE INTO player_profiles
                            (sport, team_name, player_name, position,
                             pts_per_game, reb_per_game, ast_per_game,
                             stl_per_game, blk_per_game, fg_pct, three_pct,
                             ft_pct, minutes_per_game, usage_rate,
                             impact_score, season)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            "nba", team_name, player_name, "",
                            pts, reb, ast, stl, blk,
                            fg_pct, fg3_pct, ft_pct,
                            minutes, usage, impact, season
                        ))
                    saved += 1

                except Exception as e:
                    print(f"  Save error {player_name}: {e}")

            conn.commit()
            time.sleep(2)  # Rate limit

        except Exception as e:
            print(f"  NBA {season} error: {e}")

    conn.close()
    print(f"\nNBA backfill complete: {saved} player stat records saved")


def backfill_nfl_stats():
    """Pull NFL player stats using nfl-data-py for last 5 seasons."""
    init_player_tables()

    try:
        import nfl_data_py as nfl
    except ImportError:
        print("nfl-data-py not installed. Run: pip install nfl-data-py")
        return

    # NFL team abbreviation to full name
    NFL_ABBREV = {
        "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons",
        "BAL": "Baltimore Ravens", "BUF": "Buffalo Bills",
        "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
        "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns",
        "DAL": "Dallas Cowboys", "DEN": "Denver Broncos",
        "DET": "Detroit Lions", "GB":  "Green Bay Packers",
        "HOU": "Houston Texans", "IND": "Indianapolis Colts",
        "JAX": "Jacksonville Jaguars", "KC":  "Kansas City Chiefs",
        "LAC": "Los Angeles Chargers", "LA":  "Los Angeles Rams",
        "LV":  "Las Vegas Raiders", "MIA": "Miami Dolphins",
        "MIN": "Minnesota Vikings", "NE":  "New England Patriots",
        "NO":  "New Orleans Saints", "NYG": "New York Giants",
        "NYJ": "New York Jets", "PHI": "Philadelphia Eagles",
        "PIT": "Pittsburgh Steelers", "SEA": "Seattle Seahawks",
        "SF":  "San Francisco 49ers", "TB":  "Tampa Bay Buccaneers",
        "TEN": "Tennessee Titans", "WAS": "Washington Commanders",
    }

    seasons = [2021, 2022, 2023, 2024]
    conn    = get_conn()
    c       = conn.cursor()
    saved   = 0

    print(f"\n  Pulling NFL rosters...")

    try:
        rosters = nfl.import_seasonal_rosters(seasons)
        print(f"  {len(rosters)} roster entries found")

        for _, row in rosters.iterrows():
            player_name = str(row.get("player_name", "") or "")
            team_abbrev = str(row.get("team", "") or "")
            team_name   = NFL_ABBREV.get(team_abbrev, team_abbrev)
            position    = str(row.get("position", "") or "")
            season      = str(row.get("season", "") or "")
            height      = str(row.get("height", "") or "")
            weight      = str(row.get("weight", "") or "")
            college     = str(row.get("college", "") or "")
            jersey      = str(row.get("jersey_number", "") or "")
            status      = str(row.get("status", "active") or "active")

            if not player_name:
                continue

            try:
                c.execute("""
                    INSERT OR IGNORE INTO player_stats_history
                    (sport, season, team_name, player_name, position,
                     games_played, pts_per_game, reb_per_game, ast_per_game,
                     stl_per_game, blk_per_game, fg_pct, three_pct, ft_pct,
                     minutes_per_game, usage_rate, impact_score, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "nfl", season, team_name, player_name, position,
                    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, "nfl_data_py"
                ))

                # Update current profile for 2024
                if str(season) == "2024":
                    c.execute("""
                        INSERT OR REPLACE INTO player_profiles
                        (sport, team_name, player_name, position,
                         height, weight, college, jersey_number,
                         status, impact_score, season)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        "nfl", team_name, player_name, position,
                        height, weight, college, jersey,
                        status, 0.0, season
                    ))
                saved += 1

            except Exception as e:
                continue

        conn.commit()

    except Exception as e:
        print(f"  NFL error: {e}")

    # Now pull weekly stats for impact scores
    print(f"\n  Pulling NFL weekly stats for impact scores...")
    try:
        weekly = nfl.import_weekly_data([2024])

        # Count games as number of weekly entries per player
        grouped = weekly.groupby(["player_display_name", "recent_team", "position"]).agg(
            fantasy_points=("fantasy_points", "sum"),
            games=("week", "count"),
        ).reset_index()

        for _, row in grouped.iterrows():
            player_name = str(row.get("player_display_name", "") or "")
            team_abbrev = str(row.get("recent_team", "") or "")
            team_name   = NFL_ABBREV.get(team_abbrev, team_abbrev)
            games       = int(row.get("games", 0) or 0)
            fantasy_pts = float(row.get("fantasy_points", 0) or 0)

            if not player_name or games == 0:
                continue

            pts_per_game = round(fantasy_pts / games, 1) if games > 0 else 0
            impact       = round(min(pts_per_game * 2, 100), 2)

            try:
                c.execute("""
                    UPDATE player_profiles
                    SET impact_score = ?, pts_per_game = ?
                    WHERE sport = 'nfl' AND player_name = ?
                """, (impact, pts_per_game, player_name))
            except Exception:
                continue

        conn.commit()
        print(f"  NFL impact scores updated")

    except Exception as e:
        print(f"  NFL weekly stats error: {e}")

    conn.close()
    print(f"\nNFL backfill complete: {saved} player records saved")


def print_top_nfl_players(limit: int = 10):
    """Show top NFL players by impact score."""
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT player_name, team_name, position,
               pts_per_game, impact_score
        FROM player_profiles
        WHERE sport = 'nfl' AND impact_score > 0
        ORDER BY impact_score DESC
        LIMIT ?
    """, (limit,))

    rows = c.fetchall()
    conn.close()

    print(f"\n{'='*55}")
    print(f"  TOP {limit} NFL PLAYERS BY IMPACT SCORE")
    print(f"{'='*55}")
    for r in rows:
        print(f"  {r['player_name']:<25} {r['team_name']:<25} "
              f"{r['position']:<5} Impact: {r['impact_score']:.1f}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "nba":
            backfill_nba_stats()
        elif arg == "nfl":
            backfill_nfl_stats()
            print_top_nfl_players()
        elif arg == "all":
            backfill_nba_stats()
            backfill_nfl_stats()
            print_top_nfl_players()
    else:
        print("Usage: python player_stats_backfill.py [nba|nfl|all]")