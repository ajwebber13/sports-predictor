"""
prediction_logger.py
=====================
Auto-saves every prediction to a JSON file in data/predictions/.
Run alongside telegram_alerts.py — called automatically when alerts fire.
"""

import json
import os
import requests
from datetime import datetime, timedelta

PREDICTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "predictions")
CENTRAL_OFFSET  = -5  # CDT

# ─────────────────────────────────────────────────────────────
# MODEL VERSION
# Bump this when a major layer is added to the prediction engine.
# v1 = basic Elo + power ratings
# v2 = + ensemble (XGBoost/RF/LR) + injury + home/away splits + situational
# v3 = + Elo recalibration + CLV tracker + HBCU factor (2026-06-19+)
# ─────────────────────────────────────────────────────────────
CURRENT_MODEL_VERSION = "v3"

# Version boundary dates — used to tag existing prediction files
VERSION_DATES = {
    "v1": ("2026-01-01", "2026-06-09"),   # before ensemble
    "v2": ("2026-06-10", "2026-06-18"),   # ensemble live, pre-CLV/Elo/HBCU
    "v3": ("2026-06-19", "9999-12-31"),   # current: Elo + CLV + HBCU
}

ESPN_ENDPOINTS = {
    "nfl":   "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "ncaaf": "http://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    "nba":   "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "ncaab": "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
    "ncaaw": "http://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard",
    "wnba":  "http://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
}

SEASON_TYPE_MAP = {
    1: "preseason",
    2: "regular_season",
    3: "playoff",
    4: "offseason",
}


def ensure_dir():
    os.makedirs(PREDICTIONS_DIR, exist_ok=True)


def infer_version_from_date(date_str: str) -> str:
    """Infer model version from game date for backfilling existing files."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        for version, (start, end) in VERSION_DATES.items():
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end, "%Y-%m-%d").date()
            if s <= d <= e:
                return version
    except Exception:
        pass
    return "v1"


def extract_game_date(bet: dict) -> str:
    """Pull the actual game date from commence_time if available."""
    commence_time = bet.get("commence_time", "")
    if commence_time:
        try:
            utc_dt     = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
            central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
            return central_dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now().strftime("%Y-%m-%d")


def get_game_type(sport: str, event_id: str = "", home_team: str = "", away_team: str = "") -> str:
    """
    Detect game type (regular_season, playoff, preseason) from ESPN.
    Uses event_id for exact match when available, falls back to team name match.
    Returns 'regular_season' if unable to determine.
    """
    endpoint = ESPN_ENDPOINTS.get(sport.lower())
    if not endpoint:
        return "regular_season"

    try:
        r = requests.get(endpoint, timeout=10)
        r.raise_for_status()
        data   = r.json()
        events = data.get("events", [])

        season_type  = data.get("season", {}).get("type", 2)
        default_type = SEASON_TYPE_MAP.get(season_type, "regular_season")

        for event in events:
            matched = False
            if event_id and event.get("id", "") == event_id:
                matched = True
            elif home_team or away_team:
                competitors = event.get("competitions", [{}])[0].get("competitors", [])
                names = [c.get("team", {}).get("displayName", "") for c in competitors]
                if home_team in names or away_team in names:
                    matched = True

            if matched:
                event_season_type = event.get("season", {}).get("type", season_type)
                return SEASON_TYPE_MAP.get(event_season_type, default_type)

        return default_type

    except Exception as e:
        print(f"Could not detect game type for {sport}: {e}")
        return "regular_season"


def save_prediction(bet: dict, sport: str):
    """Save a single bet/edge to a JSON prediction file."""
    ensure_dir()

    game      = bet.get("game", "unknown")
    bet_label = bet.get("bet", "")
    odds      = bet.get("odds", "N/A")
    date_str  = extract_game_date(bet)
    event_id  = bet.get("event_id", "")

    parts     = game.split(" @ ")
    away_team = parts[0] if len(parts) == 2 else ""
    home_team = parts[1] if len(parts) == 2 else ""

    game_type = get_game_type(sport, event_id, home_team, away_team)

    predicted_winner = bet_label.replace(" ML", "").replace(" +", "").replace(" -", "").strip()

    safe_game = game.replace(" @ ", "_vs_").replace(" ", "_").replace("/", "-")
    filename  = f"{date_str}_{sport}_{safe_game}.json"
    filepath  = os.path.join(PREDICTIONS_DIR, filename)

    if os.path.exists(filepath):
        print(f"  Already saved: {filename}")
        return

    data = {
        "game":          game,
        "sport":         sport,
        "date":          date_str,
        "event_id":      event_id,
        "game_type":     game_type,
        "model_version": CURRENT_MODEL_VERSION,   # ← NEW
        "bet":           bet_label,
        "odds":          odds,
        "model_prob":    bet.get("model_prob", 0),
        "implied_prob":  bet.get("implied_prob", 0),
        "edge":          round(bet.get("edge", 0) * 100, 2),
        "confidence":    bet.get("confidence", "N/A"),
        "prediction": {
            "predicted_winner": predicted_winner
        },
        "actual_result": {
            "actual_winner": ""
        }
    }

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    print(f"  Saved prediction: {filename} [{game_type}] [{CURRENT_MODEL_VERSION}]")


def save_all_predictions(bets: list, sport: str):
    """Save all bets from an alert run."""
    ensure_dir()
    saved = 0
    for bet in bets:
        save_prediction(bet, sport)
        saved += 1
    print(f"Saved {saved} predictions to data/predictions/")


def backfill_versions():
    """
    One-time utility: adds model_version to existing prediction files
    that don't have it, inferred from their game date.
    Run once: python prediction_logger.py backfill
    """
    ensure_dir()
    updated = 0
    skipped = 0
    for filename in sorted(os.listdir(PREDICTIONS_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(PREDICTIONS_DIR, filename)
        with open(filepath) as f:
            data = json.load(f)

        if data.get("model_version"):
            skipped += 1
            continue

        date_str = data.get("date", "")
        version  = infer_version_from_date(date_str)
        data["model_version"] = version

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        updated += 1

    print(f"  Backfill complete: {updated} files updated, {skipped} already tagged.")


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

    if len(sys.argv) >= 2 and sys.argv[1] == "backfill":
        backfill_versions()
        sys.exit(0)

    if len(sys.argv) >= 4 and sys.argv[1] == "update":
        game_name     = sys.argv[2]
        date_str      = sys.argv[3]
        actual_winner = sys.argv[4] if len(sys.argv) >= 5 else ""
        success = update_result(game_name, date_str, actual_winner)
        if success:
            print("Result saved. Run results_tracker.py to see updated record.")
        sys.exit(0)

    pending = list_pending_results()
    if not pending:
        print("No pending results to fill in.")
    else:
        print(f"\n{len(pending)} predictions need results:\n")
        for p in pending:
            print(f"  {p['date']} | {p['game']} | [{p.get('game_type', 'unknown')}] | [{p.get('model_version', 'untagged')}] | Bet: {p['bet']}")
        print("\nTo update a result manually, run:")
        print('  python prediction_logger.py update "Game Name" "2026-06-11" "Actual Winner"')
