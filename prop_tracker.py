"""
prop_tracker.py — Culture & Pulse Analytics
============================================
Tracks prop results over time and generates ATS-style records.

What it does:
  1. Creates prop_results table if it doesn't exist
  2. Scores today's props against ESPN box scores
  3. Reports historical records for any player/stat/line combo

Multi-sport design:
  Only WNBA has a props pipeline today. PROP_SPORT_CONFIG holds
  everything sport-specific (ESPN endpoints, game log table name).
  Adding a second sport later means adding one entry to that dict —
  not rewriting the scoring/reporting logic below it. Don't add an
  entry for a sport before its props pipeline (fetch + hit-rate +
  alert) actually exists; an empty config with no real data behind
  it just adds a silent no-op path.

Usage:
    py prop_tracker.py --score yesterday        # score yesterday's props
    py prop_tracker.py --score 2026-06-28       # score a specific date
    py prop_tracker.py --score yesterday --sport wnba  # explicit sport (default: wnba)
    py prop_tracker.py --report                 # print all prop records
    py prop_tracker.py --report "A'ja Wilson"   # print one player's records
    py prop_tracker.py --team-record "Las Vegas Aces" pts 20  # team record when player hits
    py prop_tracker.py --dry-run --score yesterday  # test without writing
"""

import os
import sys
import requests
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn

CENTRAL_OFFSET = -5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

# One entry per sport with a real props pipeline. Add a new sport here
# once its fetch/hit-rate/alert scripts exist — the scoring logic below
# picks it up automatically, same pattern as auto_results.py's SPORT_CONFIG.
PROP_SPORT_CONFIG = {
    "wnba": {
        "scoreboard_url": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
        "summary_url":    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary",
        "game_log_table": "wnba_game_log",
    },
    # "nba": {
    #     "scoreboard_url": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    #     "summary_url":    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
    #     "game_log_table": "nba_game_log",
    # },
}


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


# ── Look up a player's team ───────────────────────────────────────────────────
def get_player_team(player_name: str, sport: str = "wnba") -> str:
    """
    player_props.team_name is never actually populated by the props
    pipeline (game_home_team / game_away_team hold the matchup, not
    each player's own team) — so team lookup always goes through each
    sport's game log table instead, same approach wnba_props_alert.py
    already uses for Telegram alerts. Returns '' if no config exists
    for this sport, or no game log entry is found for this player.
    """
    config = PROP_SPORT_CONFIG.get(sport)
    if not config:
        return ""

    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT team_name FROM {config['game_log_table']}
        WHERE player_name = ?
        ORDER BY date DESC
        LIMIT 1
    """, (player_name,))
    row = c.fetchone()
    conn.close()
    return row["team_name"] if row else ""


# ── Fetch ESPN box score for a date ──────────────────────────────────────────
def fetch_espn_box_scores(date_str: str, sport: str = "wnba") -> dict:
    """
    Returns {team_name: {player_name: {stat: value, team_won: bool}}}
    Includes both single stats (pts, reb, ast, stl, blk) and combo stats
    (pr, pa, ra, pra) since props are logged using combo lines too —
    without these, any PR/PA/RA/PRA prop would always come back as
    "no data" even though the underlying box score numbers exist.
    """
    config = PROP_SPORT_CONFIG.get(sport)
    if not config:
        print(f"  No prop config for sport '{sport}' — skipping.")
        return {}

    date_fmt = date_str.replace("-", "")
    url      = f"{config['scoreboard_url']}?dates={date_fmt}"
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
        summary_url = f"{config['summary_url']}?event={game_id}"
        try:
            r2   = requests.get(summary_url, headers=HEADERS, timeout=10)
            data2 = r2.json()
            boxscore = data2.get("boxscore", {})
            print(f"    DEBUG game {game_id}: boxscore keys = {list(boxscore.keys())}, players count = {len(boxscore.get('players', []))}")

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

                    pts = gs("points")
                    reb = gs("rebounds")
                    ast = gs("assists")

                    results[t_name][p_name] = {
                        "pts":      pts,
                        "reb":      reb,
                        "ast":      ast,
                        "stl":      gs("steals"),
                        "blk":      gs("blocks"),
                        # Combo stats — required for PR/PA/RA/PRA props.
                        # None-safe: if either component is missing (DNP,
                        # bad parse), the combo is also None rather than
                        # silently computing a wrong partial total.
                        "pr":  (pts + reb) if pts is not None and reb is not None else None,
                        "pa":  (pts + ast) if pts is not None and ast is not None else None,
                        "ra":  (reb + ast) if reb is not None and ast is not None else None,
                        "pra": (pts + reb + ast) if None not in (pts, reb, ast) else None,
                        "team_won": 1 if t_won else 0,
                        "opponent": away_name if t_name == home_name else home_name,
                        "home_away": "home" if t_name == home_name else "away",
                    }
        except Exception as e:
            print(f"  Box score error ({game_id}): {e}")
            continue

    return results


# ── Score props for a date ────────────────────────────────────────────────────
def score_props(date_str: str, sport: str = "wnba", dry_run: bool = False):
    print(f"Scoring {sport.upper()} props for {date_str}...")

    if sport not in PROP_SPORT_CONFIG:
        print(f"  No prop config for sport '{sport}' — nothing to score.")
        return

    conn = get_conn()
    ensure_table(conn)

    # Get props logged for this date
    c = conn.cursor()
    c.execute("""
        SELECT * FROM player_props
        WHERE date = ? AND sport = ?
    """, (date_str, sport))
    props = [dict(r) for r in c.fetchall()]

    if not props:
        print("  No props found for this date.")
        conn.close()
        return

    print(f"  Found {len(props)} prop(s) — fetching ESPN box scores...")
    box_scores = fetch_espn_box_scores(date_str, sport=sport)

    scored = 0
    for prop in props:
        player    = prop["player_name"]
        team      = get_player_team(player, sport=sport)
        stat      = prop["stat"].lower()
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?)
            ON CONFLICT(date, player_name, stat) DO UPDATE SET
                actual_value = excluded.actual_value,
                hit          = excluded.hit,
                team_won     = excluded.team_won,
                scored_at    = excluded.scored_at
        """, (
            date_str, sport, player, team, opponent, home_away,
            stat, line, actual_value, hit, team_won,
            prop.get("over_odds"), prop.get("under_odds"),
            datetime.now(timezone.utc).isoformat()
        ))
        conn.commit()
        scored += 1

    conn.close()
    print(f"\n{'DRY RUN — ' if dry_run else ''}Scored {scored}/{len(props)} prop(s).")


# ── Report: player prop records ───────────────────────────────────────────────
def report_player(player_name: str = None, sport: str = "wnba"):
    conn = get_conn()
    ensure_table(conn)
    c    = conn.cursor()

    if player_name:
        c.execute("""
            SELECT player_name, stat, line, opponent, home_away,
                   SUM(hit) as hits, COUNT(*) as total,
                   SUM(CASE WHEN hit=1 AND team_won=1 THEN 1 ELSE 0 END) as hit_and_won
            FROM prop_results
            WHERE sport = ? AND hit IS NOT NULL
            AND player_name LIKE ?
            GROUP BY player_name, stat, line
            ORDER BY player_name, stat, total DESC
        """, (sport, f"%{player_name}%",))
    else:
        c.execute("""
            SELECT player_name, stat, line, opponent, home_away,
                   SUM(hit) as hits, COUNT(*) as total,
                   SUM(CASE WHEN hit=1 AND team_won=1 THEN 1 ELSE 0 END) as hit_and_won
            FROM prop_results
            WHERE sport = ? AND hit IS NOT NULL
            GROUP BY player_name, stat, line
            ORDER BY player_name, stat, total DESC
        """, (sport,))

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
    parser.add_argument("--sport",       default="wnba", help="Sport to score/report (default: wnba)")
    parser.add_argument("--report",      nargs="?", const="", metavar="PLAYER", help="Print prop records (optional: player name)")
    parser.add_argument("--team-record", nargs=3,  metavar=("TEAM", "STAT", "THRESHOLD"), help="Team record when player hits stat")
    parser.add_argument("--dry-run",     action="store_true")
    args = parser.parse_args()

    if args.score:
        date = parse_target_date(args.score)
        score_props(date, sport=args.sport, dry_run=args.dry_run)

    elif args.report is not None:
        report_player(args.report if args.report else None, sport=args.sport)

    elif args.team_record:
        team, stat, threshold = args.team_record
        report_team_record(team, stat, float(threshold))

    else:
        parser.print_help()
