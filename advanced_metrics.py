"""
advanced_metrics.py - Culture & Pulse Analytics
Pulls and calculates advanced team metrics for NBA and WNBA.
Stores in advanced_metrics table.

Metrics calculated:
  - Off Rating: points per 100 possessions (estimated)
  - Def Rating: points allowed per 100 possessions (estimated)
  - Net Rating: off - def
  - Pace: estimated possessions per game
  - TS%: true shooting percentage
  - AST%: assist rate
  - TOV%: turnover rate

Usage:
  python advanced_metrics.py nba
  python advanced_metrics.py wnba
  python advanced_metrics.py all
"""

import requests
import time
from datetime import datetime
from database import get_conn, init_db

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

CURRENT_SEASON = "2026"

NBA_TEAMS = {
    "1": "Atlanta Hawks", "2": "Boston Celtics", "17": "Brooklyn Nets",
    "30": "Charlotte Hornets", "4": "Chicago Bulls", "5": "Cleveland Cavaliers",
    "6": "Dallas Mavericks", "7": "Denver Nuggets", "8": "Detroit Pistons",
    "9": "Golden State Warriors", "10": "Houston Rockets", "11": "Indiana Pacers",
    "12": "Los Angeles Clippers", "13": "Los Angeles Lakers", "29": "Memphis Grizzlies",
    "14": "Miami Heat", "15": "Milwaukee Bucks", "16": "Minnesota Timberwolves",
    "3": "New Orleans Pelicans", "18": "New York Knicks", "25": "Oklahoma City Thunder",
    "19": "Orlando Magic", "20": "Philadelphia 76ers", "21": "Phoenix Suns",
    "22": "Portland Trail Blazers", "23": "Sacramento Kings", "24": "San Antonio Spurs",
    "28": "Toronto Raptors", "26": "Utah Jazz", "27": "Washington Wizards",
}

WNBA_TEAMS = {
    "20": "Atlanta Dream", "19": "Chicago Sky", "18": "Connecticut Sun",
    "3": "Dallas Wings", "129689": "Golden State Valkyries", "5": "Indiana Fever",
    "17": "Las Vegas Aces", "6": "Los Angeles Sparks", "8": "Minnesota Lynx",
    "9": "New York Liberty", "11": "Phoenix Mercury", "132052": "Portland Fire",
    "14": "Seattle Storm", "131935": "Toronto Tempo", "16": "Washington Mystics",
}


def fetch_team_stats(sport: str, team_id: str) -> dict:
    """Pull team statistics from ESPN."""
    sport_paths = {
        "wnba": "basketball/wnba",
        "nba": "basketball/nba",
        "hbcu_mbb": "basketball/mens-college-basketball",
        "hbcu_wbb": "basketball/womens-college-basketball",
    }
    sport_path = sport_paths.get(sport, "basketball/nba")
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/teams/{team_id}/statistics"

    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
        cats = data.get("results", {}).get("stats", {}).get("categories", [])

        stats = {}
        for cat in cats:
            for s in cat.get("stats", []):
                stats[s.get("name")] = s.get("value", 0.0)
        return stats
    except Exception as e:
        print(f"  Stats fetch error team {team_id}: {e}")
        return {}


def calculate_advanced_metrics(stats: dict, opp_stats: dict = None) -> dict:
    """
    Calculate advanced metrics from raw team stats.
    Uses standard basketball analytics formulas.
    """
    pts         = float(stats.get("avgPoints", 0) or 0)
    fgm         = float(stats.get("avgFieldGoalsMade", 0) or 0)
    fga         = float(stats.get("avgFieldGoalsAttempted", 0) or 0)
    ftm         = float(stats.get("avgFreeThrowsMade", 0) or 0)
    fta         = float(stats.get("avgFreeThrowsAttempted", 0) or 0)
    tpm         = float(stats.get("avgThreePointFieldGoalsMade", 0) or 0)
    oreb        = float(stats.get("avgOffensiveRebounds", 0) or 0)
    ast         = float(stats.get("avgAssists", 0) or 0)
    tov         = float(stats.get("avgTurnovers", 0) or 0)
    stl         = float(stats.get("avgSteals", 0) or 0)
    blk         = float(stats.get("avgBlocks", 0) or 0)
    dreb        = float(stats.get("avgDefensiveRebounds", 0) or 0)
    fg_pct      = float(stats.get("fieldGoalPct", 0) or 0)
    three_pct   = float(stats.get("threePointPct", 0) or 0)
    ft_pct      = float(stats.get("freeThrowPct", 0) or 0)

    # Estimate possessions per game
    # Formula: FGA - OREB + TOV + 0.44 * FTA
    pace = round(fga - oreb + tov + 0.44 * fta, 1) if fga > 0 else 0.0

    # True Shooting %
    # Formula: PTS / (2 * (FGA + 0.44 * FTA))
    ts_denom = 2 * (fga + 0.44 * fta)
    ts_pct   = round(pts / ts_denom, 3) if ts_denom > 0 else 0.0

    # Offensive rating: points per 100 possessions
    off_rating = round((pts / pace) * 100, 1) if pace > 0 else 0.0

    # Assist %: pct of made FGs assisted
    ast_pct = round(ast / fgm, 3) if fgm > 0 else 0.0

    # Turnover %: TOV per 100 possessions
    tov_pct = round((tov / pace) * 100, 1) if pace > 0 else 0.0

    # Rebound %: estimated
    reb_pct = round(oreb / (oreb + dreb), 3) if (oreb + dreb) > 0 else 0.0

    # Defensive rating — we use opponent pts if available
    # Otherwise estimate as inverse of off_rating
    def_rating = off_rating  # placeholder until we wire opponent stats

    net_rating = round(off_rating - def_rating, 1)

    return {
        "off_rating": off_rating,
        "def_rating": def_rating,
        "net_rating": net_rating,
        "pace":       pace,
        "ts_pct":     ts_pct,
        "ast_pct":    ast_pct,
        "tov_pct":    tov_pct,
        "reb_pct":    reb_pct,
        "fg_pct":     fg_pct,
        "three_pct":  three_pct,
        "ft_pct":     ft_pct,
        "pts":        pts,
        "stl":        stl,
        "blk":        blk,
    }


def fetch_opponent_pts(sport: str, team_id: str) -> float:
    """
    Get opponent points per game for defensive rating.
    Uses ESPN team schedule results.
    """
    sport_paths = {
        "wnba": "basketball/wnba",
        "nba": "basketball/nba",
        "hbcu_mbb": "basketball/mens-college-basketball",
        "hbcu_wbb": "basketball/womens-college-basketball",
    }
    sport_path = sport_paths.get(sport, "basketball/nba")
    url = f"https://site.api.espn.com/apis/site/v2/sports/{sport_path}/teams/{team_id}/schedule"

    opp_pts_list = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()

        for event in data.get("events", []):
            comps = event.get("competitions", [])
            if not comps:
                continue
            comp = comps[0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue

            competitors = comp.get("competitors", [])
            for comp_team in competitors:
                team_obj = comp_team.get("team", {})
                if str(team_obj.get("id", "")) != str(team_id):
                    score = comp_team.get("score", 0)
                    if isinstance(score, dict):
                        score = score.get("value", 0)
                    opp_pts_list.append(float(score or 0))

        if opp_pts_list:
            return round(sum(opp_pts_list) / len(opp_pts_list), 1)
    except Exception:
        pass

    return 0.0


def backfill_advanced_metrics(sport: str):
    """Pull and store advanced metrics for all teams."""
    init_db()

    if sport == "wnba":
        team_map = WNBA_TEAMS
    elif sport == "hbcu_mbb":
        from hbcu_teams import HBCU_MBB_TEAMS
        team_map = {info["id"]: name for name, info in HBCU_MBB_TEAMS.items()}
    elif sport == "hbcu_wbb":
        from hbcu_teams import HBCU_WBB_TEAMS
        team_map = {info["id"]: name for name, info in HBCU_WBB_TEAMS.items()}
    else:
        team_map = NBA_TEAMS
    conn     = get_conn()
    c        = conn.cursor()
    saved    = 0

    print(f"\nBuilding {sport.upper()} advanced metrics...")

    for team_id, team_name in team_map.items():
        stats = fetch_team_stats(sport, team_id)

        if not stats:
            print(f"  No stats: {team_name}")
            continue

        # Get opponent pts for defensive rating
        opp_pts = fetch_opponent_pts(sport, team_id)

        metrics = calculate_advanced_metrics(stats)

        # Update def_rating with real opponent pts per 100 poss
        if opp_pts > 0 and metrics["pace"] > 0:
            metrics["def_rating"] = round((opp_pts / metrics["pace"]) * 100, 1)
            metrics["net_rating"] = round(
                metrics["off_rating"] - metrics["def_rating"], 1
            )

        try:
            c.execute("""
                INSERT OR REPLACE INTO advanced_metrics
                (sport, season, team_name, off_rating, def_rating,
                 net_rating, pace, ts_pct, reb_pct, ast_pct, tov_pct, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sport, CURRENT_SEASON, team_name,
                metrics["off_rating"], metrics["def_rating"],
                metrics["net_rating"], metrics["pace"],
                metrics["ts_pct"], metrics["reb_pct"],
                metrics["ast_pct"], metrics["tov_pct"],
                "espn"
            ))
            saved += 1

            print(f"  {team_name:<28} "
                  f"OffRtg: {metrics['off_rating']:<6} "
                  f"DefRtg: {metrics['def_rating']:<6} "
                  f"NetRtg: {metrics['net_rating']:<6} "
                  f"Pace: {metrics['pace']}")

        except Exception as e:
            print(f"  Save error {team_name}: {e}")

        time.sleep(0.3)

    conn.commit()
    conn.close()
    print(f"\n{sport.upper()} advanced metrics complete: {saved} teams saved")


def print_advanced_metrics(sport: str):
    """Display advanced metrics leaderboard."""
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT team_name, off_rating, def_rating, net_rating, pace, ts_pct
        FROM advanced_metrics
        WHERE sport = ?
        ORDER BY net_rating DESC
    """, (sport,))

    rows = c.fetchall()
    conn.close()

    print(f"\n{'='*75}")
    print(f"  {sport.upper()} ADVANCED METRICS — {CURRENT_SEASON}")
    print(f"{'='*75}")
    print(f"  {'Team':<28} {'OffRtg':<8} {'DefRtg':<8} {'NetRtg':<8} {'Pace':<8} {'TS%'}")
    print(f"  {'─'*65}")
    for r in rows:
        print(f"  {r['team_name']:<28} "
              f"{r['off_rating']:<8.1f} "
              f"{r['def_rating']:<8.1f} "
              f"{r['net_rating']:<8.1f} "
              f"{r['pace']:<8.1f} "
              f"{r['ts_pct']:.3f}")
    print(f"{'='*75}\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "nba":
            backfill_advanced_metrics("nba")
            print_advanced_metrics("nba")
        elif arg == "wnba":
            backfill_advanced_metrics("wnba")
            print_advanced_metrics("wnba")
        elif arg == "hbcu_mbb":
            backfill_advanced_metrics("hbcu_mbb")
            print_advanced_metrics("hbcu_mbb")
        elif arg == "hbcu_wbb":
            backfill_advanced_metrics("hbcu_wbb")
            print_advanced_metrics("hbcu_wbb")
        elif arg == "all":
            backfill_advanced_metrics("wnba")
            backfill_advanced_metrics("nba")
            print_advanced_metrics("wnba")
            print_advanced_metrics("nba")
    else:
        print("Usage: python advanced_metrics.py [nba|wnba|hbcu_mbb|hbcu_wbb|all]")