"""
auto_results.py — Culture & Pulse Analytics
============================================
Scores yesterday's predictions against ESPN final scores, across ALL sports.
Populates the results table so recap scripts have data to report.

Usage:
    python auto_results.py yesterday             # score yesterday, all sports
    python auto_results.py yesterday --sport nfl # score just one sport
    python auto_results.py 2026-06-28
    python auto_results.py --dry-run
"""

import os
import sys
import requests
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn

CENTRAL_OFFSET = -5

# One entry per sport. Add a new sport here and auto_results.py picks it up
# automatically — no other code changes needed.
SPORT_CONFIG = {
    "wnba": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "cfb": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    "ncaab": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
    "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


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


def fetch_espn_results(date_str: str, sport: str) -> list:
    """
    Returns list of completed games with scores from ESPN for one sport.
    Each item: {game_id, home_team, away_team, home_score, away_score, actual_winner}
    game_id is ESPN's numeric event id — captured here but not yet stored in
    the predictions/results tables (that's Phase 2 of the unification).
    """
    base_url = SPORT_CONFIG.get(sport)
    if not base_url:
        print(f"  No ESPN endpoint configured for sport '{sport}' — skipping.")
        return []

    date_fmt = date_str.replace("-", "")
    url = f"{base_url}?dates={date_fmt}"
    games = []

    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  ESPN fetch error ({sport}): {e}")
        return games

    for event in data.get("events", []):
        completed = event.get("status", {}).get("type", {}).get("completed", False)
        if not completed:
            continue

        comps = event.get("competitions", [{}])
        competitors = comps[0].get("competitors", []) if comps else []
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})

        home_name = home.get("team", {}).get("displayName", "")
        away_name = away.get("team", {}).get("displayName", "")
        home_score = int(home.get("score", 0) or 0)
        away_score = int(away.get("score", 0) or 0)

        if not home_name or not away_name:
            continue

        actual_winner = home_name if home_score > away_score else away_name

        games.append({
            "game_id": event.get("id"),
            "home_team": home_name,
            "away_team": away_name,
            "home_score": home_score,
            "away_score": away_score,
            "actual_winner": actual_winner,
        })

        print(f"  [{sport.upper()}] ESPN: {away_name} @ {home_name} -> "
              f"{away_score}-{home_score} ({actual_winner} wins)")

    return games


def fetch_predictions(conn, date_str: str, sport: str) -> list:
    c = conn.cursor()
    c.execute("""
        SELECT * FROM predictions
        WHERE date = ? AND sport = ?
    """, (date_str, sport))
    return [dict(r) for r in c.fetchall()]


def match_game(prediction: dict, espn_games: list):
    """Match a prediction to an ESPN result by team name (unchanged logic)."""
    pred_home = prediction.get("home_team", "")
    pred_away = prediction.get("away_team", "")

    for g in espn_games:
        if (pred_home.lower() in g["home_team"].lower() or g["home_team"].lower() in pred_home.lower()) and \
           (pred_away.lower() in g["away_team"].lower() or g["away_team"].lower() in pred_away.lower()):
            return g
    return None


def score_prediction(prediction: dict, espn_game: dict) -> dict:
    """Determine if the prediction was correct (unchanged logic)."""
    bet = prediction.get("bet", "")
    actual_winner = espn_game["actual_winner"]

    picked_team = bet.replace(" ML", "").replace(" ml", "").strip()
    correct = 1 if picked_team.lower() in actual_winner.lower() or \
                   actual_winner.lower() in picked_team.lower() else 0

    return {
        "date": prediction["date"],
        "sport": prediction["sport"],
        "game": prediction["game"],
        "home_team": espn_game["home_team"],
        "away_team": espn_game["away_team"],
        "home_score": espn_game["home_score"],
        "away_score": espn_game["away_score"],
        "actual_winner": actual_winner,
        "prediction_id": prediction["id"],
        "correct": correct,
        "edge_at_pick": prediction.get("edge"),
        "odds_at_pick": prediction.get("odds"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def insert_result(conn, result: dict, dry_run: bool = False):
    if dry_run:
        status = "CORRECT" if result["correct"] == 1 else "WRONG"
        print(f"    [{result['sport'].upper()}] {status} -> {result['game']} -> {result['actual_winner']}")
        return

    sql = """
        INSERT INTO results (
            date, sport, game, home_team, away_team,
            home_score, away_score, actual_winner,
            prediction_id, correct, edge_at_pick, odds_at_pick, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(prediction_id) DO UPDATE SET
            home_score = excluded.home_score,
            away_score = excluded.away_score,
            actual_winner = excluded.actual_winner,
            correct = excluded.correct,
            edge_at_pick = excluded.edge_at_pick,
            odds_at_pick = excluded.odds_at_pick,
            updated_at = excluded.updated_at
    """
    params = (
        result["date"], result["sport"], result["game"],
        result["home_team"], result["away_team"],
        result["home_score"], result["away_score"], result["actual_winner"],
        result["prediction_id"], result["correct"],
        result["edge_at_pick"], result["odds_at_pick"], result["updated_at"],
    )
    conn.execute(sql, params)
    conn.commit()
    status = "CORRECT" if result["correct"] == 1 else "WRONG"
    print(f"    [{result['sport'].upper()}] {status} -> {result['game']} -> {result['actual_winner']} (saved)")


def score_prop_results(conn, date_str: str, dry_run: bool = False):
    """
    WNBA-only for now — props only exist for WNBA. Unchanged placeholder
    from the original file; full scoring pending a prop-result tracking table.
    """
    c = conn.cursor()
    c.execute("""
        SELECT * FROM player_props
        WHERE date = ? AND sport = 'wnba'
    """, (date_str,))
    props = [dict(r) for r in c.fetchall()]

    if not props:
        return
    print(f"\n  {len(props)} WNBA prop(s) logged (result tracking table pending).")


def score_sport(conn, date_str: str, sport: str, dry_run: bool = False):
    """Score one sport for one date. Returns (scored_count, prediction_count)."""
    print(f"\n--- {sport.upper()} ---")
    espn_games = fetch_espn_results(date_str, sport)
    print(f"  Found {len(espn_games)} completed game(s)")

    predictions = fetch_predictions(conn, date_str, sport)
    print(f"  Found {len(predictions)} prediction(s) logged")

    if not predictions:
        return 0, 0

    scored = 0
    for pred in predictions:
        espn_game = match_game(pred, espn_games)

        # If no match on the exact date, check the day before/after —
        # ESPN sometimes logs late games under a different calendar date.
        if not espn_game:
            for offset in (-1, 1):
                nearby_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")
                nearby_games = fetch_espn_results(nearby_date, sport)
                espn_game = match_game(pred, nearby_games)
                if espn_game:
                    print(f"    Matched via {nearby_date} instead of {date_str}")
                    break

        if not espn_game:
            print(f"    No ESPN match for: {pred.get('game')} — skipping")
            continue
        result = score_prediction(pred, espn_game)
        insert_result(conn, result, dry_run=dry_run)
        scored += 1

    if sport == "wnba":
        score_prop_results(conn, date_str, dry_run=dry_run)

    return scored, len(predictions)


def run(date_str: str, sport_filter: str = None, dry_run: bool = False):
    print(f"Scoring predictions for {date_str}...")

    sports = [sport_filter] if sport_filter else list(SPORT_CONFIG.keys())

    conn = get_conn()
    totals = {}

    for sport in sports:
        scored, total = score_sport(conn, date_str, sport, dry_run=dry_run)
        if total:
            totals[sport] = (scored, total)

    conn.close()

    print(f"\n{'DRY RUN — ' if dry_run else ''}Summary for {date_str}:")
    if not totals:
        print("  No predictions found for this date, any sport.")
        return

    for sport, (scored, total) in totals.items():
        print(f"  {sport.upper()}: scored {scored}/{total}")

    if not dry_run:
        conn2 = get_conn()
        c = conn2.cursor()
        for sport in totals:
            c.execute("""
                SELECT COUNT(*) as total, SUM(correct) as wins
                FROM results WHERE date = ? AND sport = ?
            """, (date_str, sport))
            row = c.fetchone()
            if row and row["total"]:
                losses = row["total"] - (row["wins"] or 0)
                print(f"  {sport.upper()} daily record: {row['wins'] or 0}-{losses}")
        conn2.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default="yesterday",
                         help="Date to score: 'yesterday' or YYYY-MM-DD")
    parser.add_argument("--sport", default=None,
                         help="Score only this sport (wnba, nfl, cfb, ncaab). Default: all.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print results without writing to DB")
    args = parser.parse_args()

    target = parse_target_date(args.date)
    run(target, sport_filter=args.sport, dry_run=args.dry_run)
