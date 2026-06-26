"""
backfill_odds.py — Culture & Pulse Analytics
Patches null odds in the predictions table using The Odds API historical endpoint.
Also inserts missing rows into odds_history.

Covers: June 3–17, 2026 (pre-fix window where odds saved as None)

Usage:
    python backfill_odds.py           # dry run — prints what it would patch
    python backfill_odds.py --write   # applies changes to the DB
"""

import os
import sys
import sqlite3
import requests
import time
from datetime import datetime, timezone, timedelta

API_KEY       = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

SPORT_KEYS = {
    "wnba": "basketball_wnba",
    "nba":  "basketball_nba",
}

DRY_RUN = "--write" not in sys.argv


def american_to_implied(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def get_historical_odds(sport_key: str, date_str: str) -> list:
    """
    Fetch historical odds from The Odds API for a given date.
    date_str format: YYYY-MM-DD
    Returns list of game dicts with home_team, away_team, home_ml, away_ml.
    """
    if not API_KEY:
        print("  ❌ ODDS_API_KEY not set — cannot fetch historical odds")
        return []

    # Historical endpoint requires ISO 8601 timestamp
    iso_ts = f"{date_str}T23:59:00Z"

    try:
        r = requests.get(
            f"{ODDS_API_BASE}/historical/sports/{sport_key}/odds",
            params={
                "apiKey":     API_KEY,
                "regions":    "us",
                "markets":    "h2h",
                "bookmakers": "draftkings,fanduel",
                "oddsFormat": "american",
                "date":       iso_ts,
            },
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ⚠️  Odds API error for {sport_key} {date_str}: {e}")
        return []

    games = []
    for game in data.get("data", []):
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        home_ml = away_ml = None

        for bookmaker in game.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market["key"] == "h2h":
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == home_team:
                            home_ml = outcome["price"]
                        elif outcome["name"] == away_team:
                            away_ml = outcome["price"]
                    if home_ml and away_ml:
                        break
            if home_ml and away_ml:
                break

        if home_ml and away_ml:
            games.append({
                "home_team": home_team,
                "away_team": away_team,
                "home_ml":   home_ml,
                "away_ml":   away_ml,
                "event_id":  game.get("id", ""),
            })

    return games


def normalize_name(name: str) -> str:
    """Lowercase + strip for fuzzy matching."""
    return name.lower().strip()


def find_match(db_home: str, db_away: str, api_games: list) -> dict | None:
    """Match a DB game to an API result by team name."""
    db_h = normalize_name(db_home)
    db_a = normalize_name(db_away)

    for g in api_games:
        api_h = normalize_name(g["home_team"])
        api_a = normalize_name(g["away_team"])
        # Exact match
        if db_h == api_h and db_a == api_a:
            return g
        # Partial match — handles "Golden State Valkyries" vs slight API name diff
        if db_h in api_h or api_h in db_h:
            if db_a in api_a or api_a in db_a:
                return g

    return None


def run_backfill():
    db_path = os.path.join(os.path.dirname(__file__), "cp_analytics.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Fetch all predictions missing odds
    c.execute("""
        SELECT id, date, sport, home_team, away_team
        FROM predictions
        WHERE odds IS NULL OR odds = 'N/A' OR odds = 'None'
        ORDER BY date
    """)
    bad_rows = c.fetchall()

    print(f"\n{'='*55}")
    print(f"  Odds Backfill — {'DRY RUN' if DRY_RUN else 'LIVE WRITE'}")
    print(f"  {len(bad_rows)} predictions missing odds")
    print(f"{'='*55}\n")

    if not API_KEY:
        print("❌ Set ODDS_API_KEY env var and re-run.\n")
        conn.close()
        return

    # Group by date+sport to minimize API calls
    grouped: dict[tuple, list] = {}
    for row in bad_rows:
        key = (row["date"], row["sport"])
        grouped.setdefault(key, []).append(dict(row))

    patched = 0
    missed  = 0

    for (date_str, sport), games in grouped.items():
        sport_key = SPORT_KEYS.get(sport)
        if not sport_key:
            print(f"  ⚠️  No Odds API key for sport '{sport}' — skipping {date_str}")
            missed += len(games)
            continue

        print(f"  Fetching {sport.upper()} odds for {date_str}...")
        api_games = get_historical_odds(sport_key, date_str)
        print(f"    API returned {len(api_games)} game(s)")
        time.sleep(1)  # rate limit courtesy

        for game in games:
            match = find_match(game["home_team"], game["away_team"], api_games)

            if not match:
                print(f"    ❌ No match: {game['away_team']} @ {game['home_team']}")
                missed += 1
                continue

            home_ml      = match["home_ml"]
            away_ml      = match["away_ml"]
            home_implied = round(american_to_implied(home_ml) * 100, 1)
            away_implied = round(american_to_implied(away_ml) * 100, 1)

            print(f"    ✅ {game['away_team']} @ {game['home_team']}: "
                  f"home {home_ml:+d} / away {away_ml:+d}")

            if not DRY_RUN:
                # Patch predictions.odds (stored as text like "-140" or "+115")
                odds_str = str(home_ml) if home_ml < 0 else f"+{home_ml}"
                c.execute("""
                    UPDATE predictions
                    SET odds = ?
                    WHERE id = ?
                """, (odds_str, game["id"]))

                # Insert into odds_history if not already there
                c.execute("""
                    INSERT OR IGNORE INTO odds_history
                    (date, sport, home_team, away_team,
                     home_ml, away_ml, home_implied, away_implied,
                     opening_home_ml, opening_away_ml,
                     source, captured_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    date_str, sport,
                    game["home_team"], game["away_team"],
                    home_ml, away_ml,
                    home_implied, away_implied,
                    home_ml, away_ml,  # opening = same as closing for historical
                    "odds_api_historical",
                    datetime.now(timezone.utc).isoformat(),
                ))

            patched += 1

    if not DRY_RUN:
        conn.commit()

    conn.close()

    print(f"\n{'='*55}")
    print(f"  Done. Patched: {patched}  |  Missed: {missed}")
    if DRY_RUN:
        print(f"  Run with --write to apply changes.")
    else:
        print(f"  DB updated.")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    run_backfill()
