"""
render_job.py — Culture & Pulse Analytics
Runs on Render cron schedule daily.
Fires alerts for all active sports based on season gates.
No PC required — runs entirely in the cloud.

Flags:
  --sport wnba       Run one specific sport only
  --exclude wnba     Run all sports except the specified one
  --retry            Noon retry run for missed morning picks
"""

import os
import sys
import requests
import time
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API_BASE         = "https://sports-predictor-api-44a0.onrender.com"
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"

ALL_SPORTS = ["nba", "wnba", "nfl", "cfb", "ncaab"]

SPORT_ENDPOINTS = {
    "nba":   f"{API_BASE}/nba/edges",
    "wnba":  f"{API_BASE}/wnba/edges",
    "nfl":   f"{API_BASE}/nfl/edges",
    "cfb":   f"{API_BASE}/cfb/edges",
    "ncaab": f"{API_BASE}/ncaab/edges",
}


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] {msg}", flush=True)


def wake_api():
    """Ping the API to wake Render free tier before running alerts."""
    log("Waking API...")
    try:
        requests.get(f"{API_BASE}/", timeout=60)
        time.sleep(10)
        log("API awake.")
    except Exception as e:
        log(f"Wake ping failed: {e}")


def send_telegram(text: str):
    if not TELEGRAM_TOKEN:
        log("No Telegram token — skipping.")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHANNEL, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.status_code != 200:
            log(f"Telegram error: {r.status_code} {r.text}")
    except Exception as e:
        log(f"Telegram exception: {e}")


# ─────────────────────────────────────────────────────────────
# NEW: DEDUP CHECK — prevents noon retry from re-alerting a game
# already covered by the morning alert.
#
# Matches database.py's actual schema: get_conn(), table
# "predictions", columns date / sport / game.
# ─────────────────────────────────────────────────────────────

def already_alerted_today(sport: str, game: str) -> bool:
    """
    Returns True if a pick for this game was already logged today
    (e.g. by the morning wnba_morning_alert.yml run).
    """
    try:
        from database import get_conn
        today = datetime.now().strftime("%Y-%m-%d")
        conn  = get_conn()
        cur   = conn.execute(
            "SELECT COUNT(*) as cnt FROM predictions "
            "WHERE sport = ? AND game = ? AND date = ?",
            (sport, game, today),
        )
        row = cur.fetchone()
        conn.close()
        return (row["cnt"] if row else 0) > 0
    except Exception as e:
        log(f"Dedup check failed ({e}) — defaulting to NOT alerting to avoid duplicates.")
        # Fail-safe: if we can't confirm it's new, don't send a duplicate.
        return True


# ─────────────────────────────────────────────────────────────
# ALERT RUNNER
# ─────────────────────────────────────────────────────────────

def run_alerts(sport: str, skip_if_already_alerted: bool = False) -> bool:
    log(f"Fetching {sport.upper()} edges...")

    try:
        r    = requests.get(SPORT_ENDPOINTS[sport], timeout=60)
        data = r.json()
    except Exception as e:
        log(f"API error for {sport}: {e}")
        return False

    bets = data.get("best_bets", [])

    # Auto-log today's odds to database
    try:
        from services.odds_parser import get_live_odds
        from database import log_odds, log_injuries, log_situational_factors
        games = get_live_odds(sport)
        log_odds(sport, games, source="odds_api" if games else "espn")
        log(f"Odds logged for {sport}")

        if sport == "wnba":
            try:
                from wnba_player_stats import update_recent
                update_recent(days=2)
                log("WNBA player stats updated")
            except Exception as e:
                log(f"WNBA player stats error: {e}")

        log_situational_factors(sport, games)
        log(f"Situational factors logged for {sport}")
    except Exception as e:
        log(f"Odds logging error: {e}")

    if not bets:
        log(f"No {sport.upper()} edges found today.")
        return False

    try:
        from prediction_logger import save_all_predictions, save_predictions_to_db
        save_all_predictions(bets, sport)
        save_predictions_to_db(bets, sport)
        log(f"Saved {len(bets)} predictions.")
    except Exception as e:
        log(f"Prediction logger error: {e}")

    try:
        from telegram_alerts import (
            format_header, format_alert, get_game_times,
            get_recommended_prob, format_slate_summary
        )

        game_times, game_times_raw = get_game_times(sport)

        # ── Date filter: only today's games ──
        from telegram_alerts import get_raw_time_for_bet, is_today_ct
        clean_bets = []
        suppressed = []
        for bet in bets:
            raw_time = get_raw_time_for_bet(bet, game_times_raw)
            if raw_time and not is_today_ct(raw_time):
                log(f"Skipping stale game: {bet.get('game')} — {raw_time}")
                continue

            # Confidence filter — 55% minimum based on calibration data
            recommended_prob = get_recommended_prob(bet)
            if recommended_prob < 55:
                log(f"Skipping low confidence: {bet.get('game')} — {recommended_prob}%")
                suppressed.append(bet)
                continue

            # NEW: skip games already alerted earlier today (retry runs only)
            if skip_if_already_alerted and already_alerted_today(sport, bet.get("game", "")):
                log(f"Already alerted today, skipping duplicate: {bet.get('game')}")
                continue

            clean_bets.append(bet)

        if not clean_bets:
            log(f"No {sport.upper()} bets met confidence threshold.")
            return False

        send_telegram(format_slate_summary(clean_bets, sport, suppressed=suppressed))
        time.sleep(1)

        for bet in clean_bets:
            try:
                from database import log_prediction
                log_prediction(bet, sport)
            except Exception as e:
                log(f"Prediction log error: {e}")

            game      = bet.get("game", "")
            game_time = game_times.get(game, "Time TBD")

            if game_time == "Time TBD":
                parts = game.split(" @ ")
                if len(parts) == 2:
                    game_time = game_times.get(parts[0], game_times.get(parts[1], "Time TBD"))

            send_telegram(format_alert(bet, sport, game_time))
            time.sleep(1)

        log(f"Sent {len(clean_bets)} {sport.upper()} alerts.")
        return True

    except Exception as e:
        log(f"Alert formatting error: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# RESULTS RUNNER
# ─────────────────────────────────────────────────────────────

def run_results():
    log("Pulling ESPN results...")
    try:
        from results_tracker import load_results, auto_pull_results, save_results, print_report
        results = load_results()
        results = auto_pull_results(results)
        save_results(results)
        print_report(results)
        log("Results updated.")
    except Exception as e:
        log(f"Results tracker error: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run(sports: list, retry: bool = False):
    log("══════════════════════════════════════════════")
    label = "Noon Retry" if retry else "Daily Run"
    log(f"Culture & Pulse — {label} — {datetime.now().strftime('%A %B %d, %Y')}")
    log(f"Sports: {', '.join(s.upper() for s in sports)}")
    log("══════════════════════════════════════════════")

    wake_api()

    try:
        from telegram_alerts import is_in_season
    except Exception as e:
        log(f"Could not import season gates: {e}")
        return

    for sport in sports:
        if not is_in_season(sport):
            log(f"{sport.upper()}: out of season — skipping")
            continue

        if retry:
            try:
                r    = requests.get(SPORT_ENDPOINTS[sport], timeout=60)
                data = r.json()
                bets = data.get("best_bets", [])
                if any(b.get("model_prob", 0) >= 55 for b in bets):
                    log(f"{sport.upper()}: picks found on retry — checking for duplicates")
                    # NEW: skip_if_already_alerted=True on retry runs only
                    run_alerts(sport, skip_if_already_alerted=True)
                else:
                    log(f"{sport.upper()}: still no edges on retry — skipping")

                # Capture closing line movement
                try:
                    from services.odds_parser import get_live_odds
                    from database import log_line_movement, update_closing_odds
                    games = get_live_odds(sport)
                    update_closing_odds(sport, games)
                    log_line_movement(sport, games)
                    log(f"Line movement captured for {sport}")
                except Exception as e:
                    log(f"Line movement error for {sport}: {e}")

            except Exception as e:
                log(f"Retry check error for {sport}: {e}")
        else:
            run_alerts(sport)

        time.sleep(5)

    if not retry:
        log("")
        run_results()

    log("══════════════════════════════════════════════")
    log(f"{label} complete.")
    log("══════════════════════════════════════════════")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport",   type=str, default=None,
                        help="Run one specific sport only (e.g. --sport wnba)")
    parser.add_argument("--exclude", type=str, default=None,
                        help="Exclude one sport from the run (e.g. --exclude wnba)")
    parser.add_argument("--retry",   action="store_true",
                        help="Noon retry run for missed morning picks")
    args = parser.parse_args()

    # Build sport list from flags
    if args.sport:
        sports = [args.sport.lower()]
    elif args.exclude:
        sports = [s for s in ALL_SPORTS if s != args.exclude.lower()]
    else:
        sports = ALL_SPORTS

    run(sports=sports, retry=args.retry)
