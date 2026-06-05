"""
prediction_logger.py
=====================
Auto-saves every prediction to a JSON file in data/predictions/.
Run alongside telegram_alerts.py — called automatically when alerts fire.

JSON format:
{
  "game": "New York Knicks @ San Antonio Spurs",
  "sport": "nba",
  "date": "2026-06-04",
  "bet": "New York Knicks ML",
  "odds": 180,
  "model_prob": 71.4,
  "implied_prob": 35.7,
  "edge": 35.7,
  "confidence": "NBA Net Rating Model",
  "prediction": {
    "predicted_winner": "New York Knicks"
  },
  "actual_result": {
    "actual_winner": ""
  }
}
"""

import json
import os
from datetime import datetime

PREDICTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "predictions")


def ensure_dir():
    os.makedirs(PREDICTIONS_DIR, exist_ok=True)


def save_prediction(bet: dict, sport: str):
    """Save a single bet/edge to a JSON prediction file."""
    ensure_dir()

    game      = bet.get("game", "unknown")
    bet_label = bet.get("bet", "")
    odds      = bet.get("odds", "N/A")
    today     = datetime.now().strftime("%Y-%m-%d")

    # Extract predicted winner from bet label
    # "New York Knicks ML" → "New York Knicks"
    predicted_winner = bet_label.replace(" ML", "").replace(" +", "").replace(" -", "").strip()

    # Build filename: date_sport_game.json
    safe_game = game.replace(" @ ", "_vs_").replace(" ", "_").replace("/", "-")
    filename  = f"{today}_{sport}_{safe_game}.json"
    filepath  = os.path.join(PREDICTIONS_DIR, filename)

    # Don't overwrite if already saved
    if os.path.exists(filepath):
        print(f"  Already saved: {filename}")
        return

    data = {
        "game":       game,
        "sport":      sport,
        "date":       today,
        "bet":        bet_label,
        "odds":       odds,
        "model_prob": bet.get("model_prob", 0),
        "implied_prob": bet.get("implied_prob", 0),
        "edge":       round(bet.get("edge", 0) * 100, 2),
        "confidence": bet.get("confidence", "N/A"),
        "prediction": {
            "predicted_winner": predicted_winner
        },
        "actual_result": {
            "actual_winner": ""   # Fill this in after the game
        }
    }

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    print(f"  Saved prediction: {filename}")


def save_all_predictions(bets: list, sport: str):
    """Save all bets from an alert run."""
    ensure_dir()
    saved = 0
    for bet in bets:
        save_prediction(bet, sport)
        saved += 1
    print(f"Saved {saved} predictions to data/predictions/")


def list_pending_results() -> list:
    """Return all predictions that still need actual results filled in."""
    ensure_dir()
    pending = []
    for filename in sorted(os.listdir(PREDICTIONS_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(PREDICTIONS_DIR, filename)
        with open(filepath) as f:
            data = json.load(f)
        if not data.get("actual_result", {}).get("actual_winner"):
            pending.append(data)
    return pending


def update_result(game: str, date: str, actual_winner: str) -> bool:
    """Update the actual result for a prediction."""
    ensure_dir()
    for filename in os.listdir(PREDICTIONS_DIR):
        if not filename.endswith(".json"):
            continue
        if date not in filename:
            continue
        filepath = os.path.join(PREDICTIONS_DIR, filename)
        with open(filepath) as f:
            data = json.load(f)
        if data.get("game") == game:
            data["actual_result"]["actual_winner"] = actual_winner
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            print(f"Updated result: {game} → {actual_winner}")
            return True
    print(f"Game not found: {game}")
    return False



if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "update":
        game_name     = sys.argv[2]
        date_str      = sys.argv[3]
        actual_winner = sys.argv[4] if len(sys.argv) >= 5 else ""
        success = update_result(game_name, date_str, actual_winner)
        if success:
            print("Result saved. Run evaluate.py to see accuracy.")
        sys.exit(0)

    pending = list_pending_results()
    if not pending:
        print("No pending results to fill in.")
    else:
        print(f"\n{len(pending)} predictions need results:\n")
        for p in pending:
            print(f"  {p['date']} | {p['game']} | Bet: {p['bet']} | Predicted: {p['prediction']['predicted_winner']}")
        print("\nTo update a result, run:")
        print('  python prediction_logger.py update "Game Name" "2026-06-04" "Actual Winner"')
