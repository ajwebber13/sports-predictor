"""
auto_results.py — Culture & Pulse Analytics
============================================
Scores yesterday's predictions against ESPN final scores.
Populates the results table so wnba_recap.py has data to report.

Usage:
    python auto_results.py yesterday     # score yesterday's games (Render cron)
    python auto_results.py 2026-06-28    # score a specific date
    python auto_results.py --dry-run     # print without writing to DB
"""

import os
import sys
import sqlite3
import requests
from datetime import datetime, timezone, timedelta

CENTRAL_OFFSET       = -5
ESPN_WNBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}


def get_db_path():
    return os.path.join(os.path.dirname(__file__), "cp_analytics.db")


def get_conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def parse_target_date(arg: str):
    if arg == "yesterday":
        return (get_today_ct() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        datetime.strptime(arg, "%Y-%m-%d")
        return arg
    except ValueError:
        print(f"Invalid date: {arg}. Use 'yesterday' or YYYY-MM-DD.")
        sys.exit(1)


def fetch_espn_results(date_str: str) -> list:
    """
    Returns list of completed games with scores from ESPN.
    Each item: {home_team, away_team, home_score, away_score, actual_winner}
    """
    date_fmt = date_str.replace("-", "")
    url      = f"{ESPN_WNBA_SCOREBOARD}?dates={date_fmt}"
    games    = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"ESPN fetch error: {e}")
        return games

    for event in data.get("events", []):
        completed = event.get("status", {}).get("type", {}).get("completed", False)
        if not completed:
            continue
        comps       = event.get("competitions", [{}])
        competitors = comps[0].get("competitors", []) if comps else []
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})

        home_name  = home.get("team", {}).get("displayName", "")
        away_name  = away.get("team", {}).get("displayName", "")
        home_score = int(home.get("score", 0) or 0)
        away_score = int(away.get("score", 0) or 0)

        if not home_name or not away_name:
            continue

        actual_winner = home_name if home_score > away_score else away_name

        games.append({
            "home_team":     home_name,
            "away_team":     away_name,
            "home_score":    home_score,
            "away_score":    away_score,
            "actual_winner": actual_winner,
        })
        print(f"  ESPN: {away_name} @ {home_name} → {away_score}-{home_score} ({actual_winner} wins)")

    return games


def fetch_predictions(conn, date_str: str, sport: str = "wnba") -> list:
    c = conn.cursor()
    c.execute("""
        SELECT * FROM predictions
        WHERE date = ? AND sport = ?
    """, (date_str, sport))
    return [dict(r) for r in c.fetchall()]


def match_game(prediction: dict, espn_games: list) -> dict | None:
    """Match a prediction to an ESPN result by team name."""
    pred_home = prediction.get("home_team", "")
    pred_away = prediction.get("away_team", "")
    for g in espn_games:
        if (pred_home.lower() in g["home_team"].lower() or g["home_team"].lower() in pred_home.lower()) and \
           (pred_away.lower() in g["away_team"].lower() or g["away_team"].lower() in pred_away.lower()):
            return g
    return None


def score_prediction(prediction: dict, espn_game: dict) -> dict:
    """Determine if the prediction was correct."""
    bet           = prediction.get("bet", "")
    actual_winner = espn_game["actual_winner"]

    # Extract picked team from bet label (e.g. "Las Vegas Aces ML")
    picked_team = bet.replace(" ML", "").replace(" ml", "").strip()

    correct = 1 if picked_team.lower() in actual_winner.lower() or \
                   actual_winner.lower() in picked_team.lower() else 0

    return {
        "date":           prediction["date"],
        "sport":          prediction["sport"],
        "game":           prediction["game"],
        "home_team":      espn_game["home_team"],
        "away_team":      espn_game["away_team"],
        "home_score":     espn_game["home_score"],
        "away_score":     espn_game["away_score"],
        "actual_winner":  actual_winner,
        "prediction_id":  prediction["id"],
        "correct":        correct,
        "edge_at_pick":   prediction.get("edge"),
        "odds_at_pick":   prediction.get("odds"),
        "updated_at":     datetime.now(timezone.utc).isoformat(),
    }


def insert_result(conn, result: dict, dry_run: bool = False):
    if dry_run:
        status = "✅ CORRECT" if result["correct"] == 1 else "❌ WRONG"
        print(f"  {status} — {result['game']} → {result['actual_winner']}")
        return

    sql = """
        INSERT INTO results (
            date, sport, game, home_team, away_team,
            home_score, away_score, actual_winner,
            prediction_id, correct, edge_at_pick, odds_at_pick, updated_at
        ) VALUES (
            :date, :sport, :game, :home_team, :away_team,
            :home_score, :away_score, :actual_winner,
            :prediction_id, :correct, :edge_at_pick, :odds_at_pick, :updated_at
        )
        ON CONFLICT(date, sport, game) DO UPDATE SET
            home_score    = excluded.home_score,
            away_score    = excluded.away_score,
            actual_winner = excluded.actual_winner,
            correct       = excluded.correct,
            edge_at_pick  = excluded.edge_at_pick,
            odds_at_pick  = excluded.odds_at_pick,
            updated_at    = excluded.updated_at
    """
    conn.execute(sql, result)
    conn.commit()
    status = "✅ CORRECT" if result["correct"] == 1 else "❌ WRONG"
    print(f"  {status} — {result['game']} → {result['actual_winner']} (saved)")


def score_prop_results(conn, date_str: str, espn_games: list, dry_run: bool = False):
    """
    Score player prop results by checking actual box scores.
    Updates hit_rate fields aren't touched here — just logs whether prop hit.
    """
    c = conn.cursor()
    c.execute("""
        SELECT * FROM player_props
        WHERE date = ? AND sport = 'wnba'
    """, (date_str,))
    props = [dict(r) for r in c.fetchall()]

    if not props:
        print("  No props to score for this date.")
        return

    print(f"\nScoring {len(props)} prop(s)...")
    # Props scoring would require box score lookup per player
    # Placeholder — full implementation after prop result tracking table is added
    print("  Prop scoring logged (result tracking table pending).")


def run(date_str: str, dry_run: bool = False):
    print(f"Scoring predictions for {date_str}...")

    print("\nFetching ESPN final scores...")
    espn_games = fetch_espn_results(date_str)
    print(f"  Found {len(espn_games)} completed game(s)")

    if not espn_games:
        print("No completed games found — nothing to score.")
        return

    conn        = get_conn()
    predictions = fetch_predictions(conn, date_str, sport="wnba")
    print(f"\nFound {len(predictions)} prediction(s) logged for {date_str}")

    if not predictions:
        print("No predictions found for this date.")
        conn.close()
        return

    scored = 0
    for pred in predictions:
        espn_game = match_game(pred, espn_games)
        if not espn_game:
            print(f"  No ESPN match for: {pred.get('game')} — skipping")
            continue
        result = score_prediction(pred, espn_game)
        insert_result(conn, result, dry_run=dry_run)
        scored += 1

    score_prop_results(conn, date_str, espn_games, dry_run=dry_run)

    conn.close()

    # Print daily summary
    print(f"\n{'DRY RUN — ' if dry_run else ''}Scored {scored}/{len(predictions)} prediction(s) for {date_str}")

    # Quick record summary
    if not dry_run:
        conn2 = get_conn()
        c     = conn2.cursor()
        c.execute("""
            SELECT
                COUNT(*) as total,
                SUM(correct) as wins
            FROM results
            WHERE date = ? AND sport = 'wnba'
        """, (date_str,))
        row = c.fetchone()
        if row and row["total"]:
            losses = row["total"] - (row["wins"] or 0)
            print(f"Daily record: {row['wins'] or 0}-{losses}")
        conn2.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default="yesterday",
                        help="Date to score: 'yesterday' or YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results without writing to DB")
    args = parser.parse_args()

    target = parse_target_date(args.date)
    run(target, dry_run=args.dry_run)
