"""
nba_wnba_predict.py
====================
Standalone NBA + WNBA + NCAAB prediction runner.
Primary source: The Odds API (games 24-48hrs ahead)
Fallback: ESPN scoreboard (today only)

Now includes:
  - ESPN win probability sanity check (divergence > 10pts = suppressed)
  - Confidence filter (teams with < 10 games = suppressed)
  - Injury adjustments applied BEFORE suppression check
  - Live W-L records displayed in alert slip

Usage:
  python nba_wnba_predict.py           # interactive menu
  python nba_wnba_predict.py nba       # run NBA games
  python nba_wnba_predict.py wnba      # run WNBA games
  python nba_wnba_predict.py ncaab     # run NCAAB games

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
from live_records import get_live_records, get_record
from espn_winprob import validate_pick, print_validation_result

sys.path.insert(0, os.path.dirname(__file__))


# ─────────────────────────────────────────────────────────────
# LEAGUE CONSTANTS
# ─────────────────────────────────────────────────────────────

NBA_CONSTANTS   = {"league_avg_pts": 113.0, "home_adv_pts": 3.0, "score_std_dev": 11.0}
WNBA_CONSTANTS  = {"league_avg_pts":  82.0, "home_adv_pts": 3.0, "score_std_dev": 10.0}
NCAAB_CONSTANTS = {"league_avg_pts":  72.0, "home_adv_pts": 3.5, "score_std_dev": 10.0}

MIN_WIN_PROB = 0.55   # raised from 0.45 — calibration shows sub-55% picks lose money

ODDS_API_SPORT_KEYS = {
    "NBA":   "basketball_nba",
    "WNBA":  "basketball_wnba",
    "NCAAB": "basketball_ncaab",
}

ESPN_URLS = {
    "NBA":   "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "WNBA":  "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "NCAAB": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
}


# ─────────────────────────────────────────────────────────────
# NET RATINGS -- Update each season
# ─────────────────────────────────────────────────────────────

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

# Updated June 19 2026 — cross-referenced against actual splits data
WNBA_NET_RATINGS = {
    "Minnesota Lynx":           8.2,
    "New York Liberty":         6.1,
    "Seattle Storm":            4.8,
    "Las Vegas Aces":           3.9,
    "Atlanta Dream":            3.1,
    "Indiana Fever":            2.8,
    "Dallas Wings":             2.4,
    "Portland Fire":            2.1,
    "Connecticut Sun":          1.8,
    "Chicago Sky":             -0.8,
    "Washington Mystics":      -1.4,
    "Los Angeles Sparks":      -2.1,
    "Toronto Tempo":           -2.4,
    "Phoenix Mercury":         -3.1,
    "Golden State Valkyries":  -1.5,
}

NCAAB_NET_RATINGS = {}


# ─────────────────────────────────────────────────────────────
# GAME FETCHERS
# ─────────────────────────────────────────────────────────────

def fetch_games_from_odds_api(league: str) -> list:
    if ODDS_API_KEY == "YOUR_ODDS_API_KEY_HERE":
        return []

    sport_key = ODDS_API_SPORT_KEYS.get(league)
    if not sport_key:
        return []

    ratings = _get_ratings(league)

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
                "league":    league,
                "home_team": home_name,
                "away_team": away_name,
                "game_time": game_time,
                "home_ml":   int(home_ml),
                "away_ml":   int(away_ml),
                "home_net":  ratings.get(home_name, 0.0),
                "away_net":  ratings.get(away_name, 0.0),
                "status":    "pre",
            })
        except Exception as e:
            print(f"  Parse error: {e}")

    return parsed


def fetch_games_from_espn(league: str) -> list:
    url     = ESPN_URLS.get(league)
    ratings = _get_ratings(league)
    if not url:
        return []

    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.espn.com/",
        }, timeout=10)
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
                "league":    league,
                "home_team": home_name,
                "away_team": away_name,
                "game_time": game_time,
                "home_ml":   int(home_ml) if home_ml else -110,
                "away_ml":   int(away_ml) if away_ml else +100,
                "home_net":  ratings.get(home_name, 0.0),
                "away_net":  ratings.get(away_name, 0.0),
                "status":    status,
            })
        except Exception:
            continue

    return parsed


def fetch_games(league: str) -> list:
    games = fetch_games_from_odds_api(league)
    if games:
        return games
    print("  [Odds API unavailable -- using ESPN fallback]")
    return fetch_games_from_espn(league)


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _get_ratings(league: str) -> dict:
    if league == "NBA":
        return NBA_NET_RATINGS
    if league == "WNBA":
        return WNBA_NET_RATINGS
    return NCAAB_NET_RATINGS


def _get_constants(league: str) -> dict:
    if league == "NBA":
        return NBA_CONSTANTS
    if league == "WNBA":
        return WNBA_CONSTANTS
    return NCAAB_CONSTANTS


def _get_record(team_name: str, league: str, records: dict = None) -> tuple:
    return get_record(team_name, league, records)


def _format_record(wins: int, losses: int) -> str:
    if wins == 0 and losses == 0:
        return "N/A"
    return f"{wins}-{losses}"


def implied_prob(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def simulate_game(home_net: float, away_net: float, constants: dict, sims: int = 10000,
                  home_team: str = "", away_team: str = "", league: str = "") -> tuple:
    # Try to use advanced metrics for NBA and WNBA
    home_pts = constants["league_avg_pts"] + home_net + constants["home_adv_pts"]
    away_pts = constants["league_avg_pts"] + away_net

    if home_team and away_team and league in ("NBA", "WNBA"):
        try:
            from database import get_conn
            conn = get_conn()
            c    = conn.cursor()
            sport = league.lower()

            c.execute("""
                SELECT off_rating, def_rating, pace FROM advanced_metrics
                WHERE sport = ? AND team_name = ?
                ORDER BY season DESC LIMIT 1
            """, (sport, home_team))
            home_adv = c.fetchone()

            c.execute("""
                SELECT off_rating, def_rating, pace FROM advanced_metrics
                WHERE sport = ? AND team_name = ?
                ORDER BY season DESC LIMIT 1
            """, (sport, away_team))
            away_adv = c.fetchone()
            conn.close()

            if home_adv and away_adv and home_adv["off_rating"] > 0:
                # Use real off/def ratings per 100 possessions
                pace         = (home_adv["pace"] + away_adv["pace"]) / 2
                home_off     = home_adv["off_rating"]
                home_def     = home_adv["def_rating"]
                away_off     = away_adv["off_rating"]
                away_def     = away_adv["def_rating"]

                # Expected pts = (team off + opp def) / 2 scaled by pace
                home_pts = round(((home_off + away_def) / 2 / 100) * pace + constants["home_adv_pts"], 1)
                away_pts = round(((away_off + home_def) / 2 / 100) * pace, 1)

                # Apply net rating adjustments on top
                home_pts += home_net
                away_pts += away_net

        except Exception:
            pass

    home_scores = np.random.normal(home_pts, constants["score_std_dev"], sims)
    away_scores = np.random.normal(away_pts, constants["score_std_dev"], sims)
    home_prob   = round(np.sum(home_scores > away_scores) / sims, 3)
    return home_prob, round(1 - home_prob, 3)


def pick_best_bet(home_prob, away_prob, home_ml, away_ml, home_name, away_name):
    home_edge = home_prob - implied_prob(home_ml)
    away_edge = away_prob - implied_prob(away_ml)
    if home_edge >= away_edge:
        return home_name, home_ml, home_prob, home_edge
    return away_name, away_ml, away_prob, away_edge


def _format_injury_summary(inj_list: list) -> str:
    if not inj_list:
        return ""
    significant = [i for i in inj_list if i.impact >= 0.3][:3]
    if not significant:
        return ""
    return ", ".join(f"{i.player} ({i.status})" for i in significant)


# ─────────────────────────────────────────────────────────────
# MAIN RUNNER
# ─────────────────────────────────────────────────────────────

def run_league(league: str, stake: float = 100.0):
    constants = _get_constants(league)

    static_ratings = _get_ratings(league)
    live           = get_live_ratings(league)
    ratings        = {**static_ratings, **live}

    print(f"\n{'='*60}")
    print(f"  {league} PREDICTIONS  |  Culture & Pulse Analytics")
    print(f"  {datetime.now().strftime('%A, %B %d %Y')}")
    print(f"{'='*60}")

    games = fetch_games(league)
    if not games:
        print(f"\n  No {league} games found.")
        return

    predictions = []
    suppressed  = []

    live_recs = get_live_records(league)

    for game in games:
        game["home_net"] = ratings.get(game["home_team"], game["home_net"])
        game["away_net"] = ratings.get(game["away_team"], game["away_net"])

        # ── Injury adjustments ───────────────────────────────────
        intel        = get_matchup_intel(game["home_team"], game["away_team"], league)
        home_net_adj = game["home_net"] + intel["home_injury_adj"]
        away_net_adj = game["away_net"] + intel["away_injury_adj"]

        # ── Head-to-head historical edge adjustment ──────────────
        try:
            from db_ratings import get_head_to_head_edge
            h2h_edge = get_head_to_head_edge(
                game["home_team"], game["away_team"], league
            )
            home_net_adj += h2h_edge
            if h2h_edge != 0:
                print(f"  H2H edge applied: {game['home_team']} {'+' if h2h_edge >= 0 else ''}{h2h_edge}")
        except Exception:
            pass

        # ── Situational factors adjustment ───────────────────────
        try:
            from database import get_conn
            conn  = get_conn()
            c     = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            c.execute("""
                SELECT total_adj FROM situational_factors
                WHERE date = ? AND sport = ?
                AND home_team = ? AND away_team = ?
            """, (today, league, game["home_team"], game["away_team"]))
            row = c.fetchone()
            conn.close()
            if row and row["total_adj"] != 0:
                away_net_adj += row["total_adj"]
                print(f"  Situational adj applied: {game['away_team']} {row['total_adj']}")
        except Exception:
            pass

        # ── Monte Carlo simulation ────────────────────────────────
        home_prob, away_prob = simulate_game(
            home_net_adj, away_net_adj, constants,
            home_team=game["home_team"],
            away_team=game["away_team"],
            league=league,
        )

        # ── Ensemble model blend ──────────────────────────────────
        try:
            from ensemble_model import predict_game
            ens = predict_game(game["home_team"], game["away_team"], league.lower())
            if ens and ens.get("ensemble_home_prob"):
                ens_home  = ens["ensemble_home_prob"] / 100
                ens_away  = ens["ensemble_away_prob"] / 100
                home_prob = round((home_prob * 0.5) + (ens_home * 0.5), 3)
                away_prob = round((away_prob * 0.5) + (ens_away * 0.5), 3)
                print(f"  Ensemble blend: {game['home_team']} {round(home_prob*100,1)}% "
                      f"| {game['away_team']} {round(away_prob*100,1)}%")
        except Exception:
            pass
        # ── Elo rating blend ──────────────────────────────────────
        try:
            from elo_ratings import predict_with_elo
            elo_pred = predict_with_elo(game["home_team"], game["away_team"], league.lower())
            elo_home = elo_pred["home_win_prob"] / 100
            elo_away = elo_pred["away_win_prob"] / 100
            # Blend 70% current model, 30% Elo
            home_prob = round((home_prob * 0.7) + (elo_home * 0.3), 3)
            away_prob = round((away_prob * 0.7) + (elo_away * 0.3), 3)
            print(f"  Elo blend: {game['home_team']} ({elo_pred['home_elo']}) "
                  f"{round(home_prob*100,1)}% | {game['away_team']} ({elo_pred['away_elo']}) "
                  f"{round(away_prob*100,1)}%")
        except Exception:
            pass
        # ── Home/away splits adjustment ─────────────────────────
        try:
            from home_away_splits import get_split_adjustment
            home_split_adj = get_split_adjustment(game["home_team"], league.lower(), is_home=True)
            away_split_adj = get_split_adjustment(game["away_team"], league.lower(), is_home=False)
            if home_split_adj != 0 or away_split_adj != 0:
                # Apply as a small probability nudge, scaled down since
                # this is a secondary signal on top of everything else
                net_split = (home_split_adj - away_split_adj) * 0.01
                home_prob = round(min(max(home_prob + net_split, 0.01), 0.99), 3)
                away_prob = round(1 - home_prob, 3)
                print(f"  Split adj: {game['home_team']} home {home_split_adj:+.1f} | "
                      f"{game['away_team']} away {away_split_adj:+.1f} -> "
                      f"{round(home_prob*100,1)}%/{round(away_prob*100,1)}%")
        except Exception:
            pass

        # ── Records ───────────────────────────────────────────────────
        home_w, home_l = _get_record(game["home_team"], league, live_recs)
        away_w, away_l = _get_record(game["away_team"], league, live_recs)
        home_record    = _format_record(home_w, home_l)
        away_record    = _format_record(away_w, away_l)
        # ─────────────────────────────────────────────────────────────

        # ── ESPN sanity check + confidence filter ─────────────────────
        validation = validate_pick(
            league          = league,
            home_team       = game["home_team"],
            away_team       = game["away_team"],
            model_home_prob = round(home_prob * 100, 1),
            home_wins       = home_w,
            home_losses     = home_l,
            away_wins       = away_w,
            away_losses     = away_l,
        )

        if validation["suppress"]:
            suppressed.append({
                "matchup": f"{game['away_team']} @ {game['home_team']}",
                "reason":  validation["suppress_reason"],
            })
            print(f"\n  ⚠   SUPPRESSED: {game['away_team']} @ {game['home_team']}")
            print(f"     Reason: {validation['suppress_reason']}")
            continue
        # ─────────────────────────────────────────────────────────────

        bet_team, odds, win_prob, edge = pick_best_bet(
            home_prob, away_prob,
            game["home_ml"], game["away_ml"],
            game["home_team"], game["away_team"]
        )

        # ── Minimum win probability filter ────────────────────────────
        if win_prob < MIN_WIN_PROB:
            suppressed.append({
                "matchup": f"{game['away_team']} @ {game['home_team']}",
                "reason":  f"{bet_team} win prob {round(win_prob*100,1)}% below {int(MIN_WIN_PROB*100)}% minimum threshold",
            })
            win_pct = round(win_prob * 100, 1)
            print(f"  SUPPRESSED: {game['away_team']} @ {game['home_team']}")
            print(f"     Reason: {bet_team} win prob {win_pct}% below minimum")
            continue
        # ─────────────────────────────────────────────────────────────

        if bet_team == game["home_team"]:
            opening_odds = intel.get("opening_home_odds") or game.get("opening_home")
        else:
            opening_odds = intel.get("opening_away_odds") or game.get("opening_away")

        home_inj_summary = _format_injury_summary(intel.get("home_injuries", []))
        away_inj_summary = _format_injury_summary(intel.get("away_injuries", []))

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
            home_injuries   = home_inj_summary,
            away_injuries   = away_inj_summary,
            home_record     = home_record,
            away_record     = away_record,
        )

        alert = build_alert(pred_input)
        print(f"\n{alert.formatted_slip}")
        print(format_intel_summary(intel, game["home_team"], game["away_team"]))

        if validation["espn_home_prob"] is not None:
            model_pct = round(home_prob * 100, 1)
            espn_pct  = validation["espn_home_prob"]
            gap       = validation["divergence"]["gap"]
            print(f"  📊 ESPN check: Model {model_pct}% | ESPN {espn_pct}% | Gap {gap}pts ✅")

        predictions.append(alert)

    # ── Summary ───────────────────────────────────────────────────────
    if not predictions and not suppressed:
        print(f"\n  No {league} games to predict.")
        return

    bet_it   = sum(1 for p in predictions if "BET IT"   in p.bet_quality)
    marginal = sum(1 for p in predictions if "MARGINAL" in p.bet_quality)
    passed   = sum(1 for p in predictions if "PASS"     in p.bet_quality)

    print(f"\n{'-'*60}")
    print(f"  SUMMARY -- {len(predictions)} games predicted | {len(suppressed)} suppressed")
    print(f"  BET IT: {bet_it}  |  MARGINAL: {marginal}  |  PASS: {passed}")
    if suppressed:
        print(f"\n  Suppressed picks:")
        for s in suppressed:
            print(f"    ✗ {s['matchup']} — {s['reason']}")
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


# ─────────────────────────────────────────────────────────────
# INTERACTIVE MENU
# ─────────────────────────────────────────────────────────────

def run_interactive():
    print("""
+--------------------------------------------------------------+
  SPORTS PREDICTION ENGINE  v2.2  |  Culture & Pulse Analytics
+--------------------------------------------------------------+

  Options:
    1  NBA predictions
    2  WNBA predictions
    3  NCAAB predictions
    4  All three
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
        run_league("NCAAB", stake)
    elif choice == "4":
        run_league("NBA", stake)
        run_league("WNBA", stake)
        run_league("NCAAB", stake)
    elif choice == "q":
        return
    else:
        print("  Invalid choice.")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) == 2:
        league = sys.argv[1].upper()
        if league in ("NBA", "WNBA", "NCAAB"):
            run_league(league)
        else:
            print("Usage: python nba_wnba_predict.py [nba|wnba|ncaab]")
    else:
        run_interactive()