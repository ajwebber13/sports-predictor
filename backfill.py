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
SEASONS      = list(range(CURRENT_YEAR - 5, CURRENT_YEAR + 1))

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

            c.execute("""
                INSERT OR REPLACE INTO team_stats
                (sport, season, team_name, wins, losses,
                 pts_per_game, pts_allowed, net_rating,
                 home_wins, home_losses, away_wins, away_losses, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("nba", current_season, team_name, wins, losses,
                  pts_for, pts_against, net,
                  home_w, home_l, away_w, away_l, "espn"))
            saved += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"  NBA {team_name} error: {e}")

    conn.commit()
    conn.close()
    print(f"NBA backfill complete: {saved} teams saved for {current_season}")


# ── WNBA ────────────────────────────────────────────────────────────────

def backfill_wnba(seasons: list):
    print("\n📊 Backfilling WNBA...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    WNBA_TEAM_IDS = {
        "Atlanta Dream": "3", "Chicago Sky": "5", "Connecticut Sun": "6",
        "Dallas Wings": "8", "Golden State Valkyries": "16",
        "Indiana Fever": "11", "Las Vegas Aces": "14",
        "Los Angeles Sparks": "13", "Minnesota Lynx": "9",
        "New York Liberty": "20", "Phoenix Mercury": "23",
        "Portland Fire": "17", "Seattle Storm": "26",
        "Toronto Tempo": "18", "Washington Mystics": "30",
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

            c.execute("""
                INSERT OR REPLACE INTO team_stats
                (sport, season, team_name, wins, losses,
                 pts_per_game, pts_allowed, net_rating,
                 home_wins, home_losses, away_wins, away_losses, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("wnba", current_season, team_name, wins, losses,
                  pts_for, pts_against, net,
                  home_w, home_l, away_w, away_l, "espn"))
            saved += 1
            time.sleep(0.3)

        except Exception as e:
            print(f"  WNBA {team_name} error: {e}")

    conn.commit()
    conn.close()
    print(f"WNBA backfill complete: {saved} teams saved for {current_season}")


# ── NFL ─────────────────────────────────────────────────────────────────

def backfill_nfl(seasons: list):
    print("\n📊 Backfilling NFL...")
    print("  NFL is offseason — no stats available until September.")
    print("  Skipping NFL backfill. Run again when season starts.")


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
                c.execute("""
                    INSERT OR REPLACE INTO team_stats
                    (sport, season, team_name, wins, losses, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, ("ncaaf", str(year), name, wins, losses, "cfbd"))
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

            c.execute("""
                INSERT OR REPLACE INTO team_stats
                (sport, season, team_name, wins, losses,
                 pts_per_game, pts_allowed, net_rating,
                 home_wins, home_losses, away_wins, away_losses, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("ncaab", current_season, name, wins, losses,
                  pts_for, pts_against, net,
                  home_w, home_l, away_w, away_l, "espn"))
            saved += 1
            time.sleep(0.2)

        except Exception:
            continue

    conn.commit()
    conn.close()
    print(f"NCAAB backfill complete: {saved} teams saved for {current_season}")


# ── HEAD TO HEAD ─────────────────────────────────────────────────────────

def backfill_head_to_head(sport: str, seasons: list):
    print(f"\n📊 Backfilling {sport.upper()} head-to-head results...")

    ESPN_SPORT_MAP = {
        "nba":   "basketball/nba",
        "wnba":  "basketball/wnba",
        "nfl":   "football/nfl",
        "ncaab": "basketball/mens-college-basketball",
        "ncaaf": "football/college-football",
    }

    endpoint = ESPN_SPORT_MAP.get(sport)
    if not endpoint:
        print(f"  No endpoint for {sport}")
        return

    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    for year in seasons:
        for month in range(1, 13):
            for day in [1, 15]:
                date_str = f"{year}{str(month).zfill(2)}{str(day).zfill(2)}"
                url      = (
                    f"https://site.api.espn.com/apis/site/v2/sports/"
                    f"{endpoint}/scoreboard?dates={date_str}&limit=50"
                )
                try:
                    r    = requests.get(url, headers=HEADERS, timeout=10)
                    data = r.json()

                    for event in data.get("events", []):
                        status = event.get("status", {}).get("type", {}).get("completed", False)
                        if not status:
                            continue

                        comp        = event.get("competitions", [{}])[0]
                        competitors = comp.get("competitors", [])
                        home = next((t for t in competitors if t["homeAway"] == "home"), None)
                        away = next((t for t in competitors if t["homeAway"] == "away"), None)

                        if not home or not away:
                            continue

                        home_name  = home["team"]["displayName"]
                        away_name  = away["team"]["displayName"]
                        home_score = int(home.get("score", 0))
                        away_score = int(away.get("score", 0))
                        winner     = home_name if home_score > away_score else away_name
                        game_date  = event.get("date", "")[:10]

                        c.execute("""
                            INSERT OR IGNORE INTO head_to_head
                            (sport, season, date, home_team, away_team,
                             home_score, away_score, winner, source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (sport, str(year), game_date, home_name, away_name,
                              home_score, away_score, winner, "espn"))
                        saved += 1

                    time.sleep(0.5)

                except Exception:
                    continue

        print(f"  {sport.upper()} {year}: head-to-head loaded")

    conn.commit()
    conn.close()
    print(f"{sport.upper()} head-to-head complete: {saved} records saved")


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

        if sport != "nfl":
            backfill_head_to_head(sport, SEASONS)

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