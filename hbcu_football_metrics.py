"""
hbcu_football_metrics.py - Culture & Pulse Analytics
Calculates advanced metrics for HBCU football teams (MEAC/SWAC).

Football stat structure differs from basketball - no direct
off_rating/def_rating/pace fields exist. Instead we calculate:
  - off_pts_per_game: from ESPN scoring category (totalPointsPerGame)
  - def_pts_per_game: average opponent points allowed (from schedule)
  - net_rating: off_pts_per_game - def_pts_per_game
  - sacks, tackles_for_loss: defensive pressure indicators

Stored in advanced_metrics table with sport = 'hbcu_football'.

Usage:
  python hbcu_football_metrics.py build
  python hbcu_football_metrics.py top
"""

import requests
import time
from datetime import datetime
from database import get_conn, init_db
from hbcu_teams import HBCU_FOOTBALL_TEAMS

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
CURRENT_SEASON = datetime.now().year - 1 if datetime.now().month < 8 else datetime.now().year


def fetch_team_stats(team_id: str, season: int) -> dict:
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_id}/statistics"
    try:
        r = requests.get(url, headers=HEADERS, params={"season": season}, timeout=10)
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


def fetch_opponent_pts(team_id: str, season: int) -> float:
    """Average points allowed, pulled from completed games in the schedule."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{team_id}/schedule"
    opp_pts = []
    try:
        r = requests.get(url, headers=HEADERS, params={"season": season}, timeout=10)
        data = r.json()
        for event in data.get("events", []):
            comps = event.get("competitions", [])
            if not comps:
                continue
            comp = comps[0]
            if not comp.get("status", {}).get("type", {}).get("completed"):
                continue
            for c in comp.get("competitors", []):
                team_obj = c.get("team", {})
                if str(team_obj.get("id", "")) != str(team_id):
                    score = c.get("score", 0)
                    if isinstance(score, dict):
                        score = score.get("value", 0)
                    opp_pts.append(float(score or 0))
        if opp_pts:
            return round(sum(opp_pts) / len(opp_pts), 1)
    except Exception:
        pass
    return 0.0


def build_metrics():
    init_db()
    conn = get_conn()
    c    = conn.cursor()

    print(f"\nBuilding HBCU Football advanced metrics ({CURRENT_SEASON} season)...")

    saved = 0
    for team_name, info in HBCU_FOOTBALL_TEAMS.items():
        team_id = info["id"]
        stats   = fetch_team_stats(team_id, CURRENT_SEASON)
        opp_pts = fetch_opponent_pts(team_id, CURRENT_SEASON)

        off_pts = float(stats.get("totalPointsPerGame", 0) or 0)
        sacks   = float(stats.get("sacks", 0) or 0)
        tfl     = float(stats.get("tacklesForLoss", 0) or 0)
        games   = float(stats.get("teamGamesPlayed", 0) or 1)

        net_rating = round(off_pts - opp_pts, 1)

        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
                INSERT INTO advanced_metrics
                (sport, season, team_name, off_rating, def_rating,
                 net_rating, pace, ts_pct, reb_pct, ast_pct, tov_pct, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sport, season, team_name) DO UPDATE SET
                    off_rating = EXCLUDED.off_rating,
                    def_rating = EXCLUDED.def_rating,
                    net_rating = EXCLUDED.net_rating,
                    pace       = EXCLUDED.pace,
                    ts_pct     = EXCLUDED.ts_pct,
                    reb_pct    = EXCLUDED.reb_pct,
                    ast_pct    = EXCLUDED.ast_pct,
                    tov_pct    = EXCLUDED.tov_pct,
                    source     = EXCLUDED.source,
                    updated_at = EXCLUDED.updated_at
            """, (
                "hbcu_football", str(CURRENT_SEASON), team_name,
                off_pts, opp_pts, net_rating,
                round(sacks / max(games, 1), 2),  # repurpose pace field for sacks/game
                round(tfl / max(games, 1), 2),     # repurpose ts_pct field for TFL/game
                0.0, 0.0, 0.0, "espn", now_str,
            ))
            saved += 1
            print(f"  {team_name:<38} Off: {off_pts:<6} Def: {opp_pts:<6} Net: {net_rating:+.1f}")
        except Exception as e:
            conn.rollback()
            print(f"  Save error {team_name}: {e}")

        time.sleep(0.3)

    conn.commit()
    conn.close()
    print(f"\nHBCU Football advanced metrics complete: {saved} teams saved\n")


def print_top():
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT team_name, off_rating, def_rating, net_rating
        FROM advanced_metrics
        WHERE sport = 'hbcu_football'
        ORDER BY net_rating DESC
    """)
    rows = c.fetchall()
    conn.close()

    print(f"\n{'='*65}")
    print(f"  HBCU FOOTBALL ADVANCED METRICS")
    print(f"{'='*65}")
    print(f"  {'Team':<38} {'PPG':<8} {'OppPPG':<8} {'Net'}")
    print(f"  {'-'*60}")
    for r in rows:
        print(f"  {r['team_name']:<38} {r['off_rating']:<8} {r['def_rating']:<8} {r['net_rating']:+.1f}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build_metrics()
        print_top()
    elif len(sys.argv) > 1 and sys.argv[1] == "top":
        print_top()
    else:
        print("Usage: python hbcu_football_metrics.py [build|top]")
