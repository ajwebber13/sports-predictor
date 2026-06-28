"""
prop_tracker.py — Culture & Pulse Analytics
============================================
Tracks prop results over time and generates ATS-style records.

What it does:
  1. Creates prop_results table if it doesn't exist
  2. Scores today's props against ESPN box scores
  3. Reports historical records for any player/stat/line combo

Usage:
    py prop_tracker.py --score yesterday        # score yesterday's props
    py prop_tracker.py --score 2026-06-28       # score a specific date
    py prop_tracker.py --report                 # print all prop records
    py prop_tracker.py --report "A'ja Wilson"   # print one player's records
    py prop_tracker.py --team-record "Las Vegas Aces" pts 20  # team record when player hits
    py prop_tracker.py --dry-run --score yesterday  # test without writing
"""

import os
import sys
import sqlite3
import requests
import argparse
from datetime import datetime, timezone, timedelta

CENTRAL_OFFSET       = -5
ESPN_WNBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
ESPN_WNBA_SUMMARY    = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

STAT_KEY_MAP = {
    "pts": "points",
    "reb": "rebounds",
    "ast": "assists",
    "stl": "steals",
    "blk": "blocks",
}


def get_db_path():
    return os.path.join(os.path.dirname(__file__), "cp_analytics.db")


def get_conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def parse_target_date(arg: str) -> str:
    if arg == "yesterday":
        return (get_today_ct() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        datetime.strptime(arg, "%Y-%m-%d")
        return arg
    except ValueError:
        print(f"Invalid date: {arg}")
        sys.exit(1)


# ── Create prop_results table ─────────────────────────────────────────────────
def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prop_results (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT NOT NULL,
            sport        TEXT NOT NULL DEFAULT 'wnba',
            player_name  TEXT NOT NULL,
            team_name    TEXT NOT NULL,
            opponent     TEXT NOT NULL,
            home_away    TEXT,
            stat         TEXT NOT NULL,
            line         REAL NOT NULL,
            actual_value REAL,
            hit          INTEGER,        -- 1 = over hit, 0 = under, NULL = no data
            team_won     INTEGER,        -- 1 = player's team won, 0 = lost
            over_odds    INTEGER,
            under_odds   INTEGER,
            source       TEXT DEFAULT 'manual',
            scored_at    TEXT,
            UNIQUE(date, player_name, stat)
        )
    """)
    conn.commit()


# ── Fetch ESPN box score for a date ──────────────────────────────────────────
def fetch_espn_box_scores(date_str: str) -> dict:
    """
    Returns {team_name: {player_name: {stat: value, team_won: bool}}}
    """
    date_fmt = date_str.replace("-", "")
    url      = f"{ESPN_WNBA_SCOREBOARD}?dates={date_fmt}"
    results  = {}

    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"ESPN scoreboard error: {e}")
        return results

    for event in data.get("events", []):
        completed = event.get("status", {}).get("type", {}).get("completed", False)
        if not completed:
            continue

        comps       = event.get("competitions", [{}])
        competitors = comps[0].get("competitors", []) if comps else []
        home        = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away        = next((c for c in competitors if c.get("homeAway") == "away"), {})
        home_name   = home.get("team", {}).get("displayName", "")
        away_name   = away.get("team", {}).get("displayName", "")
        home_score  = int(home.get("score", 0) or 0)
        away_score  = int(away.get("score", 0) or 0)
        home_won    = home_score > away_score

        game_id = event.get("id")
        if not game_id:
            continue

        # Fetch box score
        summary_url = f"{ESPN_WNBA_SUMMARY}?event={game_id}"
        try:
            r2   = requests.get(summary_url, headers=HEADERS, timeout=10)
            data2 = r2.json()
            boxscore = data2.get("boxscore", {})

            for team_data in boxscore.get("players", []):
                t_name = team_data.get("team", {}).get("displayName", "")
                t_won  = home_won if t_name == home_name else not home_won

                if t_name not in results:
                    results[t_name] = {}

                stats_list = team_data.get("statistics", [])
                if not stats_list:
                    continue
                stat_keys = stats_list[0].get("keys", [])
                athletes  = stats_list[0].get("athletes", [])

                for ath in athletes:
                    p_name = ath.get("athlete", {}).get("displayName", "")
                    raw    = ath.get("stats", [])
                    if not raw:
                        continue

                    def gs(key):
                        try:
                            idx = stat_keys.index(key)
                            val = raw[idx]
                            return float(val) if val not in ("N/A", "-", "", None) else None
                        except:
                            return None

                    results[t_name][p_name] = {
                        "pts":      gs("points"),
                        "reb":      gs("rebounds"),
                        "ast":      gs("assists"),
                        "stl":      gs("steals"),
                        "blk":      gs("blocks"),
                        "team_won": 1 if t_won else 0,
                        "opponent": away_name if t_name == home_name else home_name,
                        "home_away": "home" if t_name == home_name else "away",
                    }
        except Exception as e:
            print(f"  Box score error ({game_id}): {e}")
            continue

    return results


# ── Score props for a date ────────────────────────────────────────────────────
def score_props(date_str: str, dry_run: bool = False):
    print(f"Scoring props for {date_str}...")
    conn = get_conn()
    ensure_table(conn)

    # Get props logged for this date
    c = conn.cursor()
    c.execute("""
        SELECT * FROM player_props
        WHERE date = ? AND sport = 'wnba'
    """, (date_str,))
    props = [dict(r) for r in c.fetchall()]

    if not props:
        print("  No props found for this date.")
        conn.close()
        return

    print(f"  Found {len(props)} prop(s) — fetching ESPN box scores...")
    box_scores = fetch_espn_box_scores(date_str)

    scored = 0
    for prop in props:
        player    = prop["player_name"]
        team      = prop["team_name"]
        stat      = prop["stat"]
        line      = prop["line"]
        opponent  = prop.get("opponent", "")
        home_away = prop.get("home_away", "")

        # Find player in box scores
        team_data   = box_scores.get(team, {})
        player_data = team_data.get(player)

        if not player_data:
            print(f"  {player}: no box score data found — skipping")
            continue

        actual_value = player_data.get(stat)
        if actual_value is None:
            print(f"  {player} {stat.upper()}: DNP or missing — skipping")
            continue

        hit      = 1 if actual_value > line else 0
        team_won = player_data.get("team_won", None)
        status   = "✅ HIT" if hit else "❌ MISS"

        print(f"  {player} o{line} {stat.upper()}: {actual_value} — {status}")

        if dry_run:
            continue

        conn.execute("""
            INSERT INTO prop_results (
                date, sport, player_name, team_name, opponent, home_away,
                stat, line, actual_value, hit, team_won,
                over_odds, under_odds, source, scored_at
            ) VALUES (?, 'wnba', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?)
            ON CONFLICT(date, player_name, stat) DO UPDATE SET
                actual_value = excluded.actual_value,
                hit          = excluded.hit,
                team_won     = excluded.team_won,
                scored_at    = excluded.scored_at
        """, (
            date_str, player, team, opponent, home_away,
            stat, line, actual_value, hit, team_won,
            prop.get("over_odds"), prop.get("under_odds"),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        scored += 1

    conn.close()
    print(f"\n{'DRY RUN — ' if dry_run else ''}Scored {scored}/{len(props)} prop(s).")


# ── Report: player prop records ───────────────────────────────────────────────
def report_player(player_name: str = None):
    conn = get_conn()
    ensure_table(conn)
    c    = conn.cursor()

    if player_name:
        c.execute("""
            SELECT player_name, stat, line, opponent, home_away,
                   SUM(hit) as hits, COUNT(*) as total,
                   SUM(CASE WHEN hit=1 AND team_won=1 THEN 1 ELSE 0 END) as hit_and_won
            FROM prop_results
            WHERE sport = 'wnba' AND hit IS NOT NULL
            AND player_name LIKE ?
            GROUP BY player_name, stat, line
            ORDER BY player_name, stat, total DESC
        """, (f"%{player_name}%",))
    else:
        c.execute("""
            SELECT player_name, stat, line, opponent, home_away,
                   SUM(hit) as hits, COUNT(*) as total,
                   SUM(CASE WHEN hit=1 AND team_won=1 THEN 1 ELSE 0 END) as hit_and_won
            FROM prop_results
            WHERE sport = 'wnba' AND hit IS NOT NULL
            GROUP BY player_name, stat, line
            ORDER BY player_name, stat, total DESC
        """)

    rows = c.fetchall()
    conn.close()

    if not rows:
        print("No prop results recorded yet.")
        return

    print("\n📊 PROP RECORDS\n" + "─" * 40)
    current_player = None
    for row in rows:
        if row["player_name"] != current_player:
            current_player = row["player_name"]
            print(f"\n👤 {current_player}")
        hits   = row["hits"] or 0
        total  = row["total"]
        misses = total - hits
        pct    = round(hits / total * 100, 1) if total > 0 else 0
        print(f"  o{row['line']} {row['stat'].upper()}: {hits}-{misses} ({pct}%) — {total} tracked")


# ── Report: team record when player hits prop ─────────────────────────────────
def report_team_record(team_name: str, stat: str, threshold: float):
    conn = get_conn()
    ensure_table(conn)
    c    = conn.cursor()

    c.execute("""
        SELECT
            SUM(CASE WHEN actual_value >= ? AND team_won = 1 THEN 1 ELSE 0 END) as hit_wins,
            SUM(CASE WHEN actual_value >= ? THEN 1 ELSE 0 END) as hit_games,
            SUM(CASE WHEN actual_value < ? AND team_won = 1 THEN 1 ELSE 0 END) as miss_wins,
            SUM(CASE WHEN actual_value < ? THEN 1 ELSE 0 END) as miss_games
        FROM prop_results
        WHERE team_name LIKE ? AND stat = ? AND hit IS NOT NULL
    """, (threshold, threshold, threshold, threshold, f"%{team_name}%", stat))

    row = c.fetchone()
    conn.close()

    if not row or not row["hit_games"]:
        print(f"No data found for {team_name} / {stat} >= {threshold}")
        return

    hit_wins   = row["hit_wins"] or 0
    hit_games  = row["hit_games"] or 0
    miss_wins  = row["miss_wins"] or 0
    miss_games = row["miss_games"] or 0
    hit_pct    = round(hit_wins / hit_games * 100, 1) if hit_games > 0 else 0
    miss_pct   = round(miss_wins / miss_games * 100, 1) if miss_games > 0 else 0

    print(f"\n📊 TEAM RECORD — {team_name}")
    print(f"   When {stat.upper()} >= {threshold}: {hit_wins}-{hit_games - hit_wins} ({hit_pct}%)")
    if miss_games:
        print(f"   When {stat.upper()} < {threshold}:  {miss_wins}-{miss_games - miss_wins} ({miss_pct}%)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--score",       metavar="DATE", help="Score props for a date (yesterday or YYYY-MM-DD)")
    parser.add_argument("--report",      nargs="?", const="", metavar="PLAYER", help="Print prop records (optional: player name)")
    parser.add_argument("--team-record", nargs=3,  metavar=("TEAM", "STAT", "THRESHOLD"), help="Team record when player hits stat")
    parser.add_argument("--dry-run",     action="store_true")
    args = parser.parse_args()

    if args.score:
        date = parse_target_date(args.score)
        score_props(date, dry_run=args.dry_run)

    elif args.report is not None:
        report_player(args.report if args.report else None)

    elif args.team_record:
        team, stat, threshold = args.team_record
        report_team_record(team, stat, float(threshold))

    else:
        parser.print_help()
