"""
auto_results.py — Culture & Pulse Analytics
Pulls ESPN final scores and auto-scores predictions in cp_analytics.db
Run after games end — ideally via a nightly cron after 11 PM CT

Sports: NBA, WNBA, NFL, NCAAF, NCAAB
"""

import requests
import os
from datetime import datetime, timezone, timedelta
from database import get_conn

CENTRAL_OFFSET = -5

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
    "Referer":    "https://www.espn.com/",
}

ESPN_ENDPOINTS = {
    "nba":   "basketball/nba",
    "wnba":  "basketball/wnba",
    "nfl":   "football/nfl",
    "ncaaf": "football/college-football",
    "ncaab": "basketball/mens-college-basketball",
}


def get_today_ct() -> str:
    ct = datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)
    return ct.strftime("%Y-%m-%d")


def get_date_ct(days_back: int = 0) -> str:
    ct = datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET, days=-days_back)
    return ct.strftime("%Y-%m-%d")


def fetch_final_scores(sport: str, date_str: str = None) -> list:
    """
    Pull completed game scores from ESPN for a given sport and date.
    Returns list of {home_team, away_team, home_score, away_score, winner, date}
    """
    endpoint = ESPN_ENDPOINTS.get(sport)
    if not endpoint:
        return []

    if date_str:
        date_param = date_str.replace("-", "")
        url = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint}/scoreboard?dates={date_param}"
    else:
        url = f"https://site.api.espn.com/apis/site/v2/sports/{endpoint}/scoreboard"

    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"ESPN fetch error ({sport}): {e}")
        return []

    results = []
    for event in data.get("events", []):
        try:
            status = event.get("status", {}).get("type", {})
            if not status.get("completed", False):
                continue

            comp        = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home = next((t for t in competitors if t["homeAway"] == "home"), None)
            away = next((t for t in competitors if t["homeAway"] == "away"), None)

            if not home or not away:
                continue

            home_name  = home["team"]["displayName"]
            away_name  = away["team"]["displayName"]
            home_score = int(float(home.get("score", 0)))
            away_score = int(float(away.get("score", 0)))
            winner     = home_name if home_score > away_score else away_name
            game_date  = event.get("date", "")[:10]

            results.append({
                "home_team":  home_name,
                "away_team":  away_name,
                "home_score": home_score,
                "away_score": away_score,
                "winner":     winner,
                "date":       game_date,
                "game":       f"{away_name} @ {home_name}",
            })
        except Exception:
            continue

    return results


def score_predictions(sport: str, date_str: str = None) -> dict:
    """
    Match final scores to predictions and update results table.
    Returns summary of what was scored.
    """
    if not date_str:
        date_str = get_today_ct()

    print(f"\nScoring {sport.upper()} predictions for {date_str}...")
    scores = fetch_final_scores(sport, date_str)

    if not scores:
        print(f"  No completed {sport.upper()} games found for {date_str}")
        return {"scored": 0, "correct": 0, "wrong": 0}

    conn    = get_conn()
    c       = conn.cursor()
    scored  = 0
    correct = 0
    wrong   = 0

    for game_result in scores:
        game   = game_result["game"]
        winner = game_result["winner"]

        # Find matching prediction
        c.execute("""
            SELECT id, predicted_winner, edge, odds, bet
            FROM predictions
            WHERE date = ? AND sport = ?
            AND (game = ? OR game LIKE ?)
        """, (date_str, sport, game, f"%{game_result['home_team']}%"))

        pred = c.fetchone()
        if not pred:
            continue

        is_correct = 1 if pred["predicted_winner"] == winner else 0

        # Save to results table
        try:
            c.execute("""
                INSERT OR REPLACE INTO results
                (date, sport, game, home_team, away_team,
                 home_score, away_score, actual_winner,
                 prediction_id, correct, edge_at_pick, odds_at_pick)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str, sport, game,
                game_result["home_team"],
                game_result["away_team"],
                game_result["home_score"],
                game_result["away_score"],
                winner,
                pred["id"],
                is_correct,
                pred["edge"],
                pred["odds"],
            ))

            status = "✅ CORRECT" if is_correct else "❌ WRONG"
            print(f"  {game} → {winner} {status}")
            scored += 1
            if is_correct:
                correct += 1
            else:
                wrong += 1

        except Exception as e:
            print(f"  Error saving result: {e}")

    conn.commit()
    conn.close()

    print(f"  Scored: {scored} | Correct: {correct} | Wrong: {wrong}")
    return {"scored": scored, "correct": correct, "wrong": wrong}


def run_daily_scoring(days_back: int = 1):
    """
    Score predictions for yesterday by default.
    Call this nightly after games end.
    """
    date_str = get_date_ct(days_back)
    print(f"\n{'='*50}")
    print(f"Culture & Pulse — Auto Results Scorer")
    print(f"Scoring date: {date_str}")
    print(f"{'='*50}")

    sports  = ["nba", "wnba", "nfl", "ncaaf", "ncaab"]
    total   = {"scored": 0, "correct": 0, "wrong": 0}

    for sport in sports:
        result = score_predictions(sport, date_str)
        for k in total:
            total[k] += result[k]

    print(f"\n{'='*50}")
    print(f"TOTAL: Scored {total['scored']} picks")
    print(f"Correct: {total['correct']} | Wrong: {total['wrong']}")
    if total["scored"] > 0:
        win_rate = round(total["correct"] / total["scored"] * 100, 1)
        print(f"Win Rate: {win_rate}%")
    print(f"{'='*50}\n")

    return total


def print_model_report():
    """Print full model performance from DB."""
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT sport,
               COUNT(*) as picks,
               SUM(correct) as wins,
               ROUND(AVG(correct) * 100, 1) as win_rate,
               ROUND(AVG(edge_at_pick), 1) as avg_edge
        FROM results
        WHERE correct IS NOT NULL
        GROUP BY sport
        ORDER BY win_rate DESC
    """)
    rows = c.fetchall()
    conn.close()

    if not rows:
        print("\nNo results logged yet.")
        return

    print("\n📊 MODEL PERFORMANCE REPORT")
    print("─" * 55)
    print(f"{'Sport':<10} {'Picks':<8} {'Wins':<8} {'Win Rate':<12} {'Avg Edge'}")
    print("─" * 55)
    for row in rows:
        print(f"{row['sport'].upper():<10} "
              f"{row['picks']:<8} "
              f"{row['wins']:<8} "
              f"{row['win_rate']}%{'':<8} "
              f"+{row['avg_edge']}%")
    print("─" * 55)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "report":
            print_model_report()
        elif sys.argv[1] == "today":
            for sport in ["nba", "wnba", "nfl", "ncaaf", "ncaab"]:
                score_predictions(sport, get_today_ct())
            print_model_report()
        elif sys.argv[1] == "yesterday":
            run_daily_scoring(days_back=1)
            print_model_report()
        else:
            # Specific date: python auto_results.py 2026-06-14
            date_str = sys.argv[1]
            for sport in ["nba", "wnba", "nfl", "ncaaf", "ncaab"]:
                score_predictions(sport, date_str)
            print_model_report()
    else:
        run_daily_scoring(days_back=1)
        print_model_report()