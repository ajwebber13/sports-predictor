"""
nba_wnba_predict.py
====================
Standalone NBA + WNBA prediction runner.
Primary source: The Odds API (games 24-48hrs ahead)
Fallback: ESPN scoreboard (today only)

Usage:
  python nba_wnba_predict.py          # interactive menu
  python nba_wnba_predict.py nba      # run NBA games
  python nba_wnba_predict.py wnba     # run WNBA games

Requirements:
  pip install requests numpy
"""

import sys
import os
import json
import numpy as np
import requests
from datetime import datetime
from alert_engine import build_alert, PredictionInput
from intel_feed import get_matchup_intel, format_intel_summary, ODDS_API_KEY
from live_ratings import get_live_ratings

sys.path.insert(0, os.path.dirname(__file__))


# ─────────────────────────────────────────────
# LEAGUE CONSTANTS
# ─────────────────────────────────────────────

NBA_CONSTANTS  = {"league_avg_pts": 113.0, "home_adv_pts": 3.0, "score_std_dev": 11.0}
WNBA_CONSTANTS = {"league_avg_pts":  82.0, "home_adv_pts": 3.0, "score_std_dev": 10.0}

ODDS_API_SPORT_KEYS = {
    "NBA":  "basketball_nba",
    "WNBA": "basketball_wnba",
}

ESPN_NBA_URL  = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"
ESPN_WNBA_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"


# ─────────────────────────────────────────────
# NET RATINGS -- 2025-26 Regular Season
# Update each season
# ─────────────────────────────────────────────

NBA_NET_RATINGS = {
    "Oklahoma City Thunder":    11.1,
    "Detroit Pistons":           7.8,
    "Boston Celtics":            7.5,
    "San Antonio Spurs":         7.4,
    "New York Knicks":           7.0,
    "Denver Nuggets":            4.4,
    "Cleveland Cavaliers":       4.3,
    "Houston Rockets":           4.2,
    "Charlotte Hornets":         4.2,
    "Indiana Pacers":            3.1,
    "Golden State Warriors":     2.8,
    "Memphis Grizzlies":         2.1,
    "Los Angeles Lakers":        1.9,
    "Miami Heat":                1.4,
    "Minnesota Timberwolves":    0.8,
    "Philadelphia 76ers":        0.2,
    "Milwaukee Bucks":          -0.3,
    "Atlanta Hawks":            -0.8,
    "Dallas Mavericks":         -1.1,
    "Sacramento Kings":         -1.4,
    "Orlando Magic":            -1.7,
    "Toronto Raptors":          -2.2,
    "Brooklyn Nets":            -2.9,
    "Los Angeles Clippers":     -3.1,
    "New Orleans Pelicans":     -3.8,
    "Chicago Bulls":            -4.2,
    "Phoenix Suns":             -4.9,
    "Utah Jazz":                -7.1,
    "Portland Trail Blazers":   -8.3,
    "Washington Wizards":      -10.2,
}

WNBA_NET_RATINGS = {
    "Minnesota Lynx":           8.2,
    "Atlanta Dream":            5.1,
    "Dallas Wings":             4.8,
    "Indiana Fever":            3.9,
    "Portland Fire":            3.2,
    "Golden State Valkyries":   2.7,
    "Las Vegas Aces":           2.4,
    "Washington Mystics":       0.5,
    "Chicago Sky":             -1.2,
    "Toronto Tempo":           -1.8,
    "Los Angeles Sparks":      -2.1,
    "Phoenix Mercury":         -3.4,
    "Seattle Storm":           -4.6,
    "New York Liberty":        -5.2,
    "Connecticut Sun":        -16.0,
}


# ─────────────────────────────────────────────
# GAME FETCHERS
# ─────────────────────────────────────────────

def fetch_games_from_odds_api(league: str) -> list:
    """Primary source -- Odds API has games 24-48hrs ahead with live lines."""
    if ODDS_API_KEY == "YOUR_ODDS_API_KEY_HERE":
        return []

    sport_key = ODDS_API_SPORT_KEYS.get(league)
    ratings   = NBA_NET_RATINGS if league == "NBA" else WNBA_NET_RATINGS

    try:
        resp = requests.get(
            f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds",
            params={"apiKey": ODDS_API_KEY, "regions": "us",
                    "markets": "h2h", "oddsFormat": "american"},
            timeout=10
        )
        resp.raise_for_status()
        raw_games = resp.json()
    except Exception as e:
        print(f"  Odds API error: {e}")
        return []

    parsed = []
    for game in raw_games:
        try:
            home_name = game.get("home_team", "")
            away_name = game.get("away_team", "")

            commence  = game.get("commence_time", "")
            try:
                dt        = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                game_time = dt.strftime("%a %b %d - %I:%M %p CT")
            except Exception:
                game_time = commence

            home_ml, away_ml = -110, +100
            for book in game.get("bookmakers", []):
                for market in book.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == home_name:
                            home_ml = outcome["price"]
                        elif outcome["name"] == away_name:
                            away_ml = outcome["price"]
                break

            parsed.append({
                "league":       league,
                "home_team":    home_name,
                "away_team":    away_name,
                "game_time":    game_time,
                "home_ml":      int(home_ml),
                "away_ml":      int(away_ml),
                "opening_home": None,
                "opening_away": None,
                "home_net":     ratings.get(home_name, 0.0),
                "away_net":     ratings.get(away_name, 0.0),
                "status":       "pre",
            })
        except Exception as e:
            print(f"  Parse error: {e}")

    return parsed


def fetch_games_from_espn(league: str) -> list:
    """Fallback -- ESPN scoreboard, today only."""
    url     = ESPN_NBA_URL if league == "NBA" else ESPN_WNBA_URL
    ratings = NBA_NET_RATINGS if league == "NBA" else WNBA_NET_RATINGS

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception as e:
        print(f"  ESPN error: {e}")
        return []

    parsed = []
    for event in events:
        try:
            comp        = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home = next((t for t in competitors if t["homeAway"] == "home"), None)
            away = next((t for t in competitors if t["homeAway"] == "away"), None)
            if not home or not away:
                continue

            home_name = home["team"]["displayName"]
            away_name = away["team"]["displayName"]

            game_date = event.get("date", "")
            try:
                dt        = datetime.fromisoformat(game_date.replace("Z", "+00:00"))
                game_time = dt.strftime("%a %b %d - %I:%M %p CT")
            except Exception:
                game_time = game_date

            odds_data = comp.get("odds", [{}])
            odds_obj  = odds_data[0] if odds_data else {}
            home_ml   = odds_obj.get("homeTeamOdds", {}).get("moneyLine", -110)
            away_ml   = odds_obj.get("awayTeamOdds", {}).get("moneyLine", +100)
            status    = event.get("status", {}).get("type", {}).get("name", "")

            if any(x in status for x in ["Final", "STATUS_FINAL", "post"]):
                continue

            parsed.append({
                "league":       league,
                "home_team":    home_name,
                "away_team":    away_name,
                "game_time":    game_time,
                "home_ml":      int(home_ml) if home_ml else -110,
                "away_ml":      int(away_ml) if away_ml else +100,
                "opening_home": None,
                "opening_away": None,
                "home_net":     ratings.get(home_name, 0.0),
                "away_net":     ratings.get(away_name, 0.0),
                "status":       status,
            })
        except Exception:
            continue

    return parsed


def fetch_games(league: str) -> list:
    """Odds API first, ESPN fallback."""
    games = fetch_games_from_odds_api(league)
    if games:
        return games
    print("  [Odds API unavailable -- using ESPN fallback]")
    return fetch_games_from_espn(league)


# ─────────────────────────────────────────────
# PREDICTION ENGINE
# ─────────────────────────────────────────────

def implied_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def simulate_game(home_net: float, away_net: float, constants: dict, sims: int = 10000) -> tuple:
    home_scores = np.random.normal(
        constants["league_avg_pts"] + home_net + constants["home_adv_pts"],
        constants["score_std_dev"], sims
    )
    away_scores = np.random.normal(
        constants["league_avg_pts"] + away_net,
        constants["score_std_dev"], sims
    )
    home_prob = round(np.sum(home_scores > away_scores) / sims, 3)
    return home_prob, round(1 - home_prob, 3)


def pick_best_bet(home_prob, away_prob, home_ml, away_ml, home_name, away_name):
    home_edge = home_prob - implied_prob(home_ml)
    away_edge = away_prob - implied_prob(away_ml)
    if home_edge >= away_edge:
        return home_name, home_ml, home_prob, home_edge
    return away_name, away_ml, away_prob, away_edge


# ─────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────

def run_league(league: str, stake: float = 100.0):
    constants = NBA_CONSTANTS if league == "NBA" else WNBA_CONSTANTS

    # Live ratings -- falls back to static if unavailable
    static_ratings = NBA_NET_RATINGS if league == "NBA" else WNBA_NET_RATINGS
    live = get_live_ratings(league)
    ratings = {**static_ratings, **live}  # live overrides static

    print(f"\n{'='*60}")
    print(f"  {league} PREDICTIONS  |  Culture & Pulse Analytics")
    print(f"  {datetime.now().strftime('%A, %B %d %Y')}")
    print(f"{'='*60}")

    games = fetch_games(league)
    if not games:
        print(f"\n  No {league} games found.")
        return

    predictions = []

    for game in games:
        # Override with live ratings
        game["home_net"] = ratings.get(game["home_team"], game["home_net"])
        game["away_net"] = ratings.get(game["away_team"], game["away_net"])

        home_prob, away_prob = simulate_game(game["home_net"], game["away_net"], constants)
        bet_team, odds, win_prob, edge = pick_best_bet(
            home_prob, away_prob,
            game["home_ml"], game["away_ml"],
            game["home_team"], game["away_team"]
        )

        intel        = get_matchup_intel(game["home_team"], game["away_team"], league)
        home_net_adj = game["home_net"] + intel["home_injury_adj"]
        away_net_adj = game["away_net"] + intel["away_injury_adj"]

        if intel["home_injury_adj"] != 0 or intel["away_injury_adj"] != 0:
            home_prob, away_prob = simulate_game(home_net_adj, away_net_adj, constants)
            bet_team, odds, win_prob, edge = pick_best_bet(
                home_prob, away_prob,
                game["home_ml"], game["away_ml"],
                game["home_team"], game["away_team"]
            )

        if bet_team == game["home_team"]:
            opening_odds = intel.get("opening_home_odds") or game.get("opening_home")
        else:
            opening_odds = intel.get("opening_away_odds") or game.get("opening_away")

        pred_input = PredictionInput(
            sport           = league,
            home_team       = game["home_team"],
            away_team       = game["away_team"],
            game_time       = game["game_time"],
            home_win_prob   = home_prob,
            away_win_prob   = away_prob,
            bet_team        = bet_team,
            bet_type        = "ML",
            odds            = odds,
            home_net_rating = home_net_adj,
            away_net_rating = away_net_adj,
            opening_odds    = opening_odds,
            closing_odds    = None,
            stake           = stake,
        )

        alert = build_alert(pred_input)
        print(f"\n{alert.formatted_slip}")
        print(format_intel_summary(intel, game["home_team"], game["away_team"]))
        predictions.append(alert)

    if not predictions:
        print(f"\n  No {league} games to predict.")
        return

    bet_it   = sum(1 for p in predictions if "BET IT"   in p.bet_quality)
    marginal = sum(1 for p in predictions if "MARGINAL" in p.bet_quality)
    passed   = sum(1 for p in predictions if "PASS"     in p.bet_quality)

    print(f"\n{'-'*60}")
    print(f"  SUMMARY -- {len(predictions)} games analyzed")
    print(f"  BET IT: {bet_it}  |  MARGINAL: {marginal}  |  PASS: {passed}")
    print(f"{'-'*60}\n")

    ts  = datetime.now().strftime("%Y%m%d_%H%M")
    out = os.path.join(os.path.dirname(__file__), f"predictions_{league}_{ts}.json")
    with open(out, "w") as f:
        json.dump([{
            "matchup":      p.matchup,
            "bet_team":     p.bet_team,
            "odds":         p.odds,
            "ev":           p.ev_per_stake,
            "decision":     p.bet_quality,
            "win_prob":     p.win_probability,
            "clv":          p.clv_status,
            "generated_at": ts,
        } for p in predictions], f, indent=2)
    print(f"  Saved: predictions_{league}_{ts}.json")
    return predictions


# ─────────────────────────────────────────────
# INTERACTIVE MENU
# ─────────────────────────────────────────────

def run_interactive():
    print("""
+--------------------------------------------------------------+
  SPORTS PREDICTION ENGINE  v2.0  |  Culture & Pulse Analytics
+--------------------------------------------------------------+

  Options:
    1  NBA predictions
    2  WNBA predictions
    3  Both
    q  Quit
""")
    try:
        stake = float(input("  Enter stake per bet ($): $").strip())
    except ValueError:
        stake = 100.0

    choice = input("  Choose: ").strip().lower()

    if choice == "1":
        run_league("NBA", stake)
    elif choice == "2":
        run_league("WNBA", stake)
    elif choice == "3":
        run_league("NBA", stake)
        run_league("WNBA", stake)
    elif choice == "q":
        return
    else:
        print("  Invalid choice.")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) == 2:
        league = sys.argv[1].upper()
        if league in ("NBA", "WNBA"):
            run_league(league)
        else:
            print("Usage: python nba_wnba_predict.py [nba|wnba]")
    else:
        run_interactive()
