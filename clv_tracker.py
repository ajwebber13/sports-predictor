"""
clv_tracker.py - Culture & Pulse Analytics
Closing Line Value tracker.

CLV measures whether your model finds real edge by checking if
the market moves toward your pick after you take it. Consistently
beating the closing line is stronger proof of model quality than
win rate alone, since win rate is subject to short-term variance.

How it works:
  1. log_pick()    - called at alert time, saves opening odds
  2. update_clv()  - called near game time, fetches closing odds
                     and calculates CLV
  3. report()      - shows full CLV history and summary stats

CLV calculation:
  Opening implied prob = 1 / (1 + 100/abs(odds)) for favorites
  Closing implied prob = same formula with closing odds
  CLV = closing implied - opening implied
  Positive CLV = market moved toward your pick (good)
  Negative CLV = market moved against your pick (bad)

Usage:
  python clv_tracker.py report          # show CLV summary
  python clv_tracker.py update          # fetch closing odds for pending picks
  python clv_tracker.py check wnba      # check current WNBA odds
"""

import os
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
CLV_LOG      = os.path.join(os.path.dirname(__file__), "clv_log.json")

SPORT_KEYS = {
    "wnba":  "basketball_wnba",
    "nba":   "basketball_nba",
    "nfl":   "americanfootball_nfl",
    "ncaaf": "americanfootball_ncaaf",
    "ncaab": "basketball_ncaab",
}

PRIMARY_BOOK   = "draftkings"
FALLBACK_BOOKS = ["fanduel", "betmgm", "betonlineag", "bovada"]


def load_clv_log() -> list:
    if os.path.exists(CLV_LOG):
        with open(CLV_LOG) as f:
            return json.load(f)
    return []


def save_clv_log(data: list):
    with open(CLV_LOG, "w") as f:
        json.dump(data, f, indent=2)


def american_to_implied(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds > 0:
        return round(100 / (odds + 100), 4)
    else:
        return round(abs(odds) / (abs(odds) + 100), 4)


def implied_to_american(prob: float) -> int:
    """Convert implied probability to American odds."""
    if prob >= 0.5:
        return round(-(prob / (1 - prob)) * 100)
    else:
        return round((1 - prob) / prob * 100)


def get_book_odds(game_data: dict, team: str, book_key: str) -> int:
    """Extract odds for a specific team from a specific bookmaker."""
    for bm in game_data.get("bookmakers", []):
        if bm["key"] != book_key:
            continue
        for market in bm.get("markets", []):
            if market["key"] != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                if outcome["name"].lower() == team.lower():
                    return outcome["price"]
    return None


def get_consensus_odds(game_data: dict, team: str) -> int:
    """Average implied probability across all available books, convert back to American."""
    probs = []
    for bm in game_data.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                if outcome["name"].lower() == team.lower():
                    probs.append(american_to_implied(outcome["price"]))

    if not probs:
        return None
    avg_prob = sum(probs) / len(probs)
    return implied_to_american(avg_prob)


def fetch_current_odds(sport: str) -> list:
    """Fetch current odds from The Odds API for a sport."""
    sport_key = SPORT_KEYS.get(sport.lower())
    if not sport_key or not ODDS_API_KEY:
        return []
    try:
        r = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
            params={
                "apiKey":      ODDS_API_KEY,
                "regions":     "us",
                "markets":     "h2h",
                "oddsFormat":  "american",
            },
            timeout=10,
        )
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def find_game(odds_data: list, home_team: str, away_team: str) -> dict:
    """Find a specific game in odds data by team name fuzzy match."""
    for game in odds_data:
        h = game.get("home_team", "").lower()
        a = game.get("away_team", "").lower()
        if (home_team.lower() in h or h in home_team.lower()) and \
           (away_team.lower() in a or a in away_team.lower()):
            return game
    return None


def log_pick(sport: str, home_team: str, away_team: str,
             bet_team: str, model_prob: float, edge: float):
    """
    Called at alert time. Fetches and logs opening odds for a pick.
    This is the starting point for CLV tracking.
    """
    log = load_clv_log()

    game_key = f"{away_team} @ {home_team} ({sport.upper()})"
    for entry in log:
        if entry["game"] == game_key and entry["status"] == "pending":
            return

    odds_data    = fetch_current_odds(sport)
    game         = find_game(odds_data, home_team, away_team) if odds_data else None
    opening_odds = None
    consensus    = None

    if game:
        opening_odds = get_book_odds(game, bet_team, PRIMARY_BOOK)
        if not opening_odds:
            for book in FALLBACK_BOOKS:
                opening_odds = get_book_odds(game, bet_team, book)
                if opening_odds:
                    break
        consensus = get_consensus_odds(game, bet_team)
        commence  = game.get("commence_time", "")
    else:
        commence = ""

    opening_implied = american_to_implied(opening_odds) if opening_odds else None

    entry = {
        "game":             game_key,
        "sport":            sport.upper(),
        "home_team":        home_team,
        "away_team":        away_team,
        "bet_team":         bet_team,
        "commence_time":    commence,
        "model_prob":       model_prob,
        "edge_at_open":     edge,
        "opening_odds_dk":  opening_odds,
        "opening_odds_consensus": consensus,
        "opening_implied":  opening_implied,
        "closing_odds_dk":  None,
        "closing_odds_consensus": None,
        "closing_implied":  None,
        "clv":              None,
        "clv_consensus":    None,
        "status":           "pending",
        "logged_at":        datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    log.append(entry)
    save_clv_log(log)
    print(f"  CLV logged: {game_key} | Opening DK: {opening_odds} | Consensus: {consensus}")


def update_clv():
    """
    Fetch current (closing) odds for all pending picks and calculate CLV.
    Run this close to game time or after games complete.
    """
    log = load_clv_log()
    updated = 0

    for entry in log:
        if entry["status"] != "pending":
            continue

        sport     = entry["sport"].lower()
        home      = entry["home_team"]
        away      = entry["away_team"]
        bet_team  = entry["bet_team"]

        odds_data = fetch_current_odds(sport)
        game      = find_game(odds_data, home, away) if odds_data else None

        if not game:
            continue

        closing_dk        = get_book_odds(game, bet_team, PRIMARY_BOOK)
        closing_consensus = get_consensus_odds(game, bet_team)

        if not closing_dk and not closing_consensus:
            continue

        closing_implied = american_to_implied(closing_dk) if closing_dk else None
        opening_implied = entry.get("opening_implied")

        clv          = None
        clv_consensus = None

        if closing_implied and opening_implied:
            clv = round(closing_implied - opening_implied, 4)

        if closing_consensus and entry.get("opening_odds_consensus"):
            open_cons_implied    = american_to_implied(entry["opening_odds_consensus"])
            closing_cons_implied = american_to_implied(closing_consensus)
            clv_consensus = round(closing_cons_implied - open_cons_implied, 4)

        entry["closing_odds_dk"]        = closing_dk
        entry["closing_odds_consensus"] = closing_consensus
        entry["closing_implied"]        = closing_implied
        entry["clv"]                    = clv
        entry["clv_consensus"]          = clv_consensus
        entry["status"]                 = "closed"
        entry["closed_at"]              = datetime.now().strftime("%Y-%m-%d %H:%M")
        updated += 1

    save_clv_log(log)
    print(f"CLV updated: {updated} picks closed")


def report():
    """Print full CLV report with summary stats."""
    log = load_clv_log()

    if not log:
        print("No CLV data logged yet.")
        return

    closed   = [e for e in log if e["status"] == "closed" and e["clv"] is not None]
    pending  = [e for e in log if e["status"] == "pending"]

    print(f"\n{'='*65}")
    print(f"  CLV REPORT — Culture & Pulse Analytics")
    print(f"{'='*65}")

    if closed:
        avg_clv     = round(sum(e["clv"] for e in closed) / len(closed) * 100, 2)
        positive    = sum(1 for e in closed if e["clv"] > 0)
        negative    = sum(1 for e in closed if e["clv"] < 0)
        beat_pct    = round(positive / len(closed) * 100, 1)

        print(f"\n  Picks with CLV data: {len(closed)}")
        print(f"  Avg CLV:             {avg_clv:+.2f}%")
        print(f"  Beat closing line:   {positive}/{len(closed)} ({beat_pct}%)")
        print(f"  Lost closing line:   {negative}/{len(closed)}")

        print(f"\n  {'Game':<35} {'Open':>6} {'Close':>7} {'CLV':>7}")
        print(f"  {'-'*58}")
        for e in closed:
            clv_str = f"{e['clv']*100:+.1f}%" if e['clv'] is not None else "N/A"
            print(f"  {e['game'][:34]:<35} "
                  f"{str(e['opening_odds_dk'] or 'N/A'):>6} "
                  f"{str(e['closing_odds_dk'] or 'N/A'):>7} "
                  f"{clv_str:>7}")
    else:
        print("\n  No closed picks with CLV data yet.")

    if pending:
        print(f"\n  Pending picks (opening odds logged, awaiting close):")
        for e in pending:
            print(f"    {e['game']} | Open DK: {e['opening_odds_dk']} | Logged: {e['logged_at']}")

    print(f"\n{'='*65}\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "report":
            report()
        elif cmd == "update":
            update_clv()
            report()
        elif cmd == "check":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            odds  = fetch_current_odds(sport)
            print(f"\n{sport.upper()} games with odds: {len(odds)}")
            for g in odds:
                print(f"  {g['away_team']} @ {g['home_team']} | {g['commence_time'][:10]}")
    else:
        report()
