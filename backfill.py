"""
backfill.py — Culture & Pulse Analytics
Pulls 5 years of historical team stats and loads into cp_analytics.db
Sports: NBA, WNBA, NFL, NCAAB, NCAAF

Sources:
  NBA/WNBA  → ESPN free API
  NFL       → ESPN free API
  NCAAF     → College Football Data API (free, no key)
  NCAAB     → ESPN free API

Run once to backfill. Then nightly updates keep it current.
"""

import requests
import sqlite3
import os
import time
from datetime import datetime
from database import get_conn, init_db

CURRENT_YEAR = 2026
SEASONS      = list(range(CURRENT_YEAR - 5, CURRENT_YEAR + 1))  # 2021-2026

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

    for year in seasons:
        season_str = f"{year-1}-{str(year)[2:]}"
        url        = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams"
        try:
            r     = requests.get(url, headers=HEADERS, timeout=10)
            data  = r.json()
            teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])

            for entry in teams:
                team         = entry.get("team", {})
                name         = team.get("displayName", "")
                record_items = team.get("record", {}).get("items", [])
                wins = losses = 0
                for item in record_items:
                    if item.get("type") == "total":
                        stats  = {s["name"]: s["value"] for s in item.get("stats", [])}
                        wins   = int(stats.get("wins", 0))
                        losses = int(stats.get("losses", 0))
                if not name:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO team_stats
                    (sport, season, team_name, wins, losses, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, ("nba", season_str, name, wins, losses, "espn"))
                saved += 1

            print(f"  NBA {season_str}: {len(teams)} teams loaded")
            time.sleep(1)

        except Exception as e:
            print(f"  NBA {season_str} error: {e}")

    conn.commit()
    conn.close()
    print(f"NBA backfill complete: {saved} records saved")


# ── WNBA ────────────────────────────────────────────────────────────────

def backfill_wnba(seasons: list):
    print("\n📊 Backfilling WNBA...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    for year in seasons:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams"
        try:
            r     = requests.get(url, headers=HEADERS, timeout=10)
            data  = r.json()
            teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])

            for entry in teams:
                team         = entry.get("team", {})
                name         = team.get("displayName", "")
                record_items = team.get("record", {}).get("items", [])
                wins = losses = 0
                for item in record_items:
                    if item.get("type") == "total":
                        stats  = {s["name"]: s["value"] for s in item.get("stats", [])}
                        wins   = int(stats.get("wins", 0))
                        losses = int(stats.get("losses", 0))
                if not name:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO team_stats
                    (sport, season, team_name, wins, losses, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, ("wnba", str(year), name, wins, losses, "espn"))
                saved += 1

            print(f"  WNBA {year}: {len(teams)} teams loaded")
            time.sleep(1)

        except Exception as e:
            print(f"  WNBA {year} error: {e}")

    conn.commit()
    conn.close()
    print(f"WNBA backfill complete: {saved} records saved")


# ── NFL ─────────────────────────────────────────────────────────────────

def backfill_nfl(seasons: list):
    print("\n📊 Backfilling NFL...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    for year in seasons:
        url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
        try:
            r     = requests.get(url, headers=HEADERS, timeout=10)
            data  = r.json()
            teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])

            for entry in teams:
                team         = entry.get("team", {})
                name         = team.get("displayName", "")
                record_items = team.get("record", {}).get("items", [])
                wins = losses = 0
                for item in record_items:
                    if item.get("type") == "total":
                        stats  = {s["name"]: s["value"] for s in item.get("stats", [])}
                        wins   = int(stats.get("wins", 0))
                        losses = int(stats.get("losses", 0))
                if not name:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO team_stats
                    (sport, season, team_name, wins, losses, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, ("nfl", str(year), name, wins, losses, "espn"))
                saved += 1

            print(f"  NFL {year}: {len(teams)} teams loaded")
            time.sleep(1)

        except Exception as e:
            print(f"  NFL {year} error: {e}")

    conn.commit()
    conn.close()
    print(f"NFL backfill complete: {saved} records saved")


# ── NCAAF ───────────────────────────────────────────────────────────────

def backfill_ncaaf(seasons: list):
    print("\n📊 Backfilling NCAAF (College Football Data API)...")
    conn  = get_conn()
    c     = conn.cursor()
    saved = 0

    cfbd_key  = os.getenv("CFBD_API_KEY", "")
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

    for year in seasons:
        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams?limit=200"
        try:
            r     = requests.get(url, headers=HEADERS, timeout=10)
            data  = r.json()
            teams = data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])

            for entry in teams:
                team         = entry.get("team", {})
                name         = team.get("displayName", "")
                record_items = team.get("record", {}).get("items", [])
                wins = losses = 0
                for item in record_items:
                    if item.get("type") == "total":
                        stats  = {s["name"]: s["value"] for s in item.get("stats", [])}
                        wins   = int(stats.get("wins", 0))
                        losses = int(stats.get("losses", 0))
                if not name:
                    continue
                c.execute("""
                    INSERT OR REPLACE INTO team_stats
                    (sport, season, team_name, wins, losses, source)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, ("ncaab", str(year), name, wins, losses, "espn"))
                saved += 1

            print(f"  NCAAB {year}: {len(teams)} teams loaded")
            time.sleep(1)

        except Exception as e:
            print(f"  NCAAB {year} error: {e}")

    conn.commit()
    conn.close()
    print(f"NCAAB backfill complete: {saved} records saved")


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