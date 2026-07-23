"""
backfill.py — Culture & Pulse Analytics
Pulls current season team stats and loads into cp_analytics.db
Sports: NBA, WNBA, NFL, NCAAB, NCAAF
"""

import requests
import os
import time
from datetime import datetime
from database import get_conn, init_db

CURRENT_YEAR = 2026
SEASONS      = list(range(CURRENT_YEAR - 10, CURRENT_YEAR + 1))  # 2016-2026

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}


# ── NBA ─────────────────────────────────────────────────────────────────

def backfill_nba(seasons: list):
    print("\n📊 Backfilling NBA...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

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

    current_season = f"{CURRENT_YEAR-1}-{str(CURRENT_YEAR)[2:]}"
    print(f"  Pulling current season stats ({current_season})...")

    for team_name, team_id in NBA_TEAM_IDS.items():
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}"
        try:
            r    = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()
            team = data.get("team", {})

            wins = losses = 0
            pts_for = pts_against = net = 0.0
            home_w = home_l = away_w = away_l = 0

            for item in team.get("record", {}).get("items", []):
                stats = {s["name"]: s["value"] for s in item.get("stats", [])}
                if item.get("type") == "total":
                    wins        = int(stats.get("wins", 0))
                    losses      = int(stats.get("losses", 0))
                    pts_for     = round(float(stats.get("avgPointsFor") or 0), 2)
                    pts_against = round(float(stats.get("avgPointsAgainst") or 0), 2)
                    net         = round(float(stats.get("differential") or 0), 2)
                elif item.get("type") == "home":
                    home_w = int(stats.get("wins", 0))
                    home_l = int(stats.get("losses", 0))
                elif item.get("type") == "road":
                    away_w = int(stats.get("wins", 0))
                    away_l = int(stats.get("losses", 0))

            if wins == 0 and pts_for == 0:
                continue

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
                INSERT INTO team_stats
                (sport, season, team_name, wins, losses,
                 points_for, points_against, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sport, season, team_name) DO UPDATE SET
                    wins           = EXCLUDED.wins,
                    losses         = EXCLUDED.losses,
                    points_for     = EXCLUDED.points_for,
                    points_against = EXCLUDED.points_against,
                    source         = EXCLUDED.source,
                    updated_at     = EXCLUDED.updated_at
            """, ("nba", current_season, team_name, wins, losses,
                  pts_for, pts_against, "espn", now_str))
            saved += 1
            print(f"    {team_name}: {wins}-{losses}, net {net:+.1f} "
                  f"(home {home_w}-{home_l}, away {away_w}-{away_l})")
            time.sleep(0.3)

        except Exception as e:
            conn.rollback()
            print(f"  NBA {team_name} error: {e}")

    conn.commit()
    conn.close()
    print(f"NBA backfill complete: {saved} teams saved for {current_season}")


# ── WNBA ────────────────────────────────────────────────────────────────

# ── WNBA ────────────────────────────────────────────────────────────────

def backfill_wnba(seasons: list):
    print("\n📊 Backfilling WNBA...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

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

    current_season = str(CURRENT_YEAR)
    print(f"  Pulling current season stats ({current_season})...")

    for team_name, team_id in WNBA_TEAM_IDS.items():
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/{team_id}"
        try:
            r    = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()
            team = data.get("team", {})

            wins = losses = 0
            pts_for = pts_against = net = 0.0
            home_w = home_l = away_w = away_l = 0

            for item in team.get("record", {}).get("items", []):
                stats = {s["name"]: s["value"] for s in item.get("stats", [])}
                if item.get("type") == "total":
                    wins        = int(stats.get("wins", 0))
                    losses      = int(stats.get("losses", 0))
                    pts_for     = round(float(stats.get("avgPointsFor") or 0), 2)
                    pts_against = round(float(stats.get("avgPointsAgainst") or 0), 2)
                    net         = round(float(stats.get("differential") or 0), 2)
                elif item.get("type") == "home":
                    home_w = int(stats.get("wins", 0))
                    home_l = int(stats.get("losses", 0))
                elif item.get("type") == "road":
                    away_w = int(stats.get("wins", 0))
                    away_l = int(stats.get("losses", 0))

            if wins == 0 and pts_for == 0:
                print(f"  Skipping {team_name} — no stats returned")
                continue

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
                INSERT INTO team_stats
                (sport, season, team_name, wins, losses,
                 points_for, points_against, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sport, season, team_name) DO UPDATE SET
                    wins           = EXCLUDED.wins,
                    losses         = EXCLUDED.losses,
                    points_for     = EXCLUDED.points_for,
                    points_against = EXCLUDED.points_against,
                    source         = EXCLUDED.source,
                    updated_at     = EXCLUDED.updated_at
            """, ("wnba", current_season, team_name, wins, losses,
                  pts_for, pts_against, "espn", now_str))
            saved += 1
            print(f"    {team_name}: {wins}-{losses}, net {net:+.1f} "
                  f"(home {home_w}-{home_l}, away {away_w}-{away_l})")
            time.sleep(0.3)

        except Exception as e:
            conn.rollback()
            print(f"  WNBA {team_name} error: {e}")

    conn.commit()
    conn.close()
    print(f"WNBA backfill complete: {saved} teams saved for {current_season}")

# ── NFL ─────────────────────────────────────────────────────────────────

def backfill_nfl(seasons: list):
    print("\n📊 Backfilling NFL (ESPN Core API - historical by season)...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    NFL_TEAM_IDS = {
        "Atlanta Falcons": "1", "Buffalo Bills": "2", "Chicago Bears": "3",
        "Cincinnati Bengals": "4", "Cleveland Browns": "5", "Dallas Cowboys": "6",
        "Denver Broncos": "7", "Detroit Lions": "8", "Green Bay Packers": "9",
        "Tennessee Titans": "10", "Indianapolis Colts": "11", "Kansas City Chiefs": "12",
        "Las Vegas Raiders": "13", "Los Angeles Rams": "14", "Miami Dolphins": "15",
        "Minnesota Vikings": "16", "New England Patriots": "17", "New Orleans Saints": "18",
        "New York Giants": "19", "New York Jets": "20", "Philadelphia Eagles": "21",
        "Arizona Cardinals": "22", "Pittsburgh Steelers": "23", "Los Angeles Chargers": "24",
        "San Francisco 49ers": "25", "Seattle Seahawks": "26", "Tampa Bay Buccaneers": "27",
        "Washington Commanders": "28", "Carolina Panthers": "29", "Jacksonville Jaguars": "30",
        "Baltimore Ravens": "33", "Houston Texans": "34",
    }

    for year in seasons:
        loaded = 0
        print(f"  NFL {year}...")

        for team_name, team_id in NFL_TEAM_IDS.items():
            url = (
                f"https://sports.core.api.espn.com/v2/sports/football/"
                f"leagues/nfl/seasons/{year}/types/2/teams/{team_id}/records/0"
            )
            try:
                r    = requests.get(url, headers=HEADERS, timeout=10)
                if r.status_code != 200:
                    continue
                data  = r.json()
                stats = {s["name"]: s["value"] for s in data.get("stats", [])}

                wins        = int(stats.get("wins", 0))
                losses      = int(stats.get("losses", 0))
                pts_for     = round(float(stats.get("avgPointsFor") or 0), 2)
                pts_against = round(float(stats.get("avgPointsAgainst") or 0), 2)
                net         = round(float(stats.get("differential") or 0), 2)

                if wins == 0 and pts_for == 0:
                    continue

                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("""
                    INSERT INTO team_stats
                    (sport, season, team_name, wins, losses,
                     points_for, points_against, source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (sport, season, team_name) DO UPDATE SET
                        wins           = EXCLUDED.wins,
                        losses         = EXCLUDED.losses,
                        points_for     = EXCLUDED.points_for,
                        points_against = EXCLUDED.points_against,
                        source         = EXCLUDED.source,
                        updated_at     = EXCLUDED.updated_at
                """, ("nfl", str(year), team_name, wins, losses,
                      pts_for, pts_against, "espn_core", now_str))
                saved  += 1
                loaded += 1
                print(f"    {team_name}: {wins}-{losses}, net {net:+.1f}")
                time.sleep(0.2)

            except Exception as e:
                conn.rollback()
                print(f"  NFL {team_name} {year} error: {e}")

        print(f"  NFL {year}: {loaded} teams loaded")

    conn.commit()
    conn.close()
    print(f"NFL backfill complete: {saved} records saved")

# ── NCAAF ───────────────────────────────────────────────────────────────

def backfill_ncaaf(seasons: list):
    print("\n📊 Backfilling NCAAF (College Football Data API)...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    cfbd_key     = os.getenv("CFBD_API_KEY", "")
    cfbd_headers = {**HEADERS, "Authorization": f"Bearer {cfbd_key}"}

    for year in seasons:
        url = "https://api.collegefootballdata.com/teams"
        try:
            r    = requests.get(url, headers=cfbd_headers, timeout=10)
            data = r.json()
            if not isinstance(data, list):
                print(f"  NCAAF API error: {data}")
                continue

            rec_url = f"https://api.collegefootballdata.com/records?year={year}"
            rec_r   = requests.get(rec_url, headers=cfbd_headers, timeout=10)
            records = {t["team"]: t for t in rec_r.json()} if rec_r.ok else {}

            team_list = data if isinstance(data, list) else []

            for team in team_list[:130]:
                if not isinstance(team, dict):
                    continue
                name = team.get("school", "")
                if not name:
                    continue
                rec    = records.get(name, {})
                total  = rec.get("total", {})
                wins   = total.get("wins", 0)
                losses = total.get("losses", 0)
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                c.execute("""
                    INSERT INTO team_stats
                    (sport, season, team_name, wins, losses, source, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (sport, season, team_name) DO UPDATE SET
                        wins       = EXCLUDED.wins,
                        losses     = EXCLUDED.losses,
                        source     = EXCLUDED.source,
                        updated_at = EXCLUDED.updated_at
                """, ("ncaaf", str(year), name, wins, losses, "cfbd", now_str))
                saved += 1

            print(f"  NCAAF {year}: records loaded")
            time.sleep(2)

        except Exception as e:
            print(f"  NCAAF {year} error: {e}")

    conn.commit()
    conn.close()
    print(f"NCAAF backfill complete: {saved} records saved")


# ── NCAAB ───────────────────────────────────────────────────────────────

def backfill_ncaab(seasons: list):
    print("\n📊 Backfilling NCAAB...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    # Pull team list with IDs from ESPN
    url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams?limit=200"
    try:
        r     = requests.get(url, headers=HEADERS, timeout=10)
        data  = r.json()
        teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
    except Exception as e:
        print(f"  NCAAB team list error: {e}")
        conn.close()
        return

    current_season = str(CURRENT_YEAR)
    print(f"  Pulling current season stats ({current_season})...")
    print(f"  Found {len(teams)} teams")

    for entry in teams:
        team    = entry.get("team", {})
        name    = team.get("displayName", "")
        team_id = team.get("id", "")

        if not name or not team_id:
            continue

        team_url = (
            f"https://site.api.espn.com/apis/site/v2/sports/"
            f"basketball/mens-college-basketball/teams/{team_id}"
        )
        try:
            r         = requests.get(team_url, headers=HEADERS, timeout=10)
            data      = r.json()
            team_data = data.get("team", {})

            wins = losses = 0
            pts_for = pts_against = net = 0.0
            home_w = home_l = away_w = away_l = 0

            for item in team_data.get("record", {}).get("items", []):
                stats = {s["name"]: s["value"] for s in item.get("stats", [])}
                if item.get("type") == "total":
                    wins        = int(stats.get("wins", 0))
                    losses      = int(stats.get("losses", 0))
                    pts_for     = round(float(stats.get("avgPointsFor") or 0), 2)
                    pts_against = round(float(stats.get("avgPointsAgainst") or 0), 2)
                    net         = round(float(stats.get("differential") or 0), 2)
                elif item.get("type") == "home":
                    home_w = int(stats.get("wins", 0))
                    home_l = int(stats.get("losses", 0))
                elif item.get("type") == "road":
                    away_w = int(stats.get("wins", 0))
                    away_l = int(stats.get("losses", 0))

            if wins == 0 and pts_for == 0:
                continue

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
                INSERT INTO team_stats
                (sport, season, team_name, wins, losses,
                 points_for, points_against, source, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (sport, season, team_name) DO UPDATE SET
                    wins           = EXCLUDED.wins,
                    losses         = EXCLUDED.losses,
                    points_for     = EXCLUDED.points_for,
                    points_against = EXCLUDED.points_against,
                    source         = EXCLUDED.source,
                    updated_at     = EXCLUDED.updated_at
            """, ("ncaab", current_season, name, wins, losses,
                  pts_for, pts_against, "espn", now_str))
            saved += 1
            print(f"    {name}: {wins}-{losses}, net {net:+.1f} "
                  f"(home {home_w}-{home_l}, away {away_w}-{away_l})")
            time.sleep(0.2)

        except Exception:
            conn.rollback()
            continue
    print(f"NCAAB backfill complete: {saved} teams saved for {current_season}")


# ── HEAD TO HEAD ─────────────────────────────────────────────────────────

def backfill_head_to_head(sport: str, seasons: list):
    """MIGRATION NOTE (2026-07-14): disabled, not converted.

    Confirmed against the live Turso database that a head_to_head
    table does not exist and never has (SELECT sql FROM sqlite_master
    WHERE type='table' AND name='head_to_head' returns no rows). This
    function has therefore never saved a single row in production —
    every call's INSERT would have failed with "no such table", caught
    silently by the bare `except Exception: continue` inside the loop.

    This isn't a migration bug to fix by inventing a matching table in
    schema_postgres.sql; it's a feature that was never actually built.
    schema_postgres.sql is meant to be the one source of truth for
    what's real in production, so adding a table here to catch up with
    dead code would misrepresent that. If head-to-head tracking is
    wanted, it's a fresh feature to design (schema, then this function),
    not something this migration should patch in as a side effect."""
    print(f"  backfill_head_to_head() is disabled — head_to_head table "
          f"was never created in production; this never wrote data. "
          f"Skipping {sport}.")
    return


# ── MAIN ────────────────────────────────────────────────────────────────

def run_backfill(sports: list = None):
    init_db()

    if not sports:
        sports = ["nba", "wnba", "nfl", "ncaaf", "ncaab"]

    print(f"\n{'='*50}")
    print(f"Culture & Pulse — Historical Backfill")
    print(f"Seasons: {SEASONS[0]} — {SEASONS[-1]}")
    print(f"Sports: {', '.join(s.upper() for s in sports)}")
    print(f"{'='*50}")

    for sport in sports:
        if sport == "nba":
            backfill_nba(SEASONS)
        elif sport == "wnba":
            backfill_wnba(SEASONS)
        elif sport == "nfl":
            backfill_nfl(SEASONS)
        elif sport == "ncaaf":
            backfill_ncaaf(SEASONS)
        elif sport == "ncaab":
            backfill_ncaab(SEASONS)

        # head-to-head backfill removed from the default run — see
        # backfill_head_to_head()'s docstring above.

    print(f"\n{'='*50}")
    print("Backfill complete.")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        sports = sys.argv[1:]
        run_backfill(sports)
    else:
        run_backfill()