"""
render_job.py — Culture & Pulse Analytics
Runs on Render cron schedule daily.
Fires alerts for all active sports based on season gates.
No PC required — runs entirely in the cloud.
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

SPORTS = ["nba", "wnba", "nfl", "ncaaf", "ncaab"]

SPORT_ENDPOINTS = {
    "nba":   f"{API_BASE}/nba/edges",
    "wnba":  f"{API_BASE}/wnba/edges",
    "nfl":   f"{API_BASE}/nfl/edges",
    "ncaaf": f"{API_BASE}/ncaaf/edges",
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
# ALERT RUNNER
# Returns True if alerts were sent, False if nothing fired
# ─────────────────────────────────────────────────────────────

def run_alerts(sport: str) -> bool:
    log(f"Fetching {sport.upper()} edges...")

    try:
        r    = requests.get(SPORT_ENDPOINTS[sport], timeout=60)
        data = r.json()
    except Exception as e:
        log(f"API error for {sport}: {e}")
        return False

    bets = data.get("best_bets", [])

    if not bets:
        log(f"No {sport.upper()} edges found today.")
        return False

    try:
        from prediction_logger import save_all_predictions
        save_all_predictions(bets, sport)
        log(f"Saved {len(bets)} predictions.")
    except Exception as e:
        log(f"Prediction logger error: {e}")

    try:
        from telegram_alerts import (
            format_header, format_alert, get_game_times
        )

        game_times, game_times_raw = get_game_times(sport)

        clean_bets = []
        for bet in bets:
            prob = bet.get("model_prob", 50)
            if prob >= 55:
                clean_bets.append(bet)
            else:
                log(f"Skipping low confidence: {bet.get('game')} — {prob}%")

        if not clean_bets:
            log("No bets met confidence threshold.")
            return False

        send_telegram(format_header(clean_bets, sport))
        time.sleep(1)

        for bet in clean_bets:
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

def run(retry: bool = False):
    log("══════════════════════════════════════════════")
    label = "Noon Retry" if retry else "Daily Run"
    log(f"Culture & Pulse — {label} — {datetime.now().strftime('%A %B %d, %Y')}")
    log("══════════════════════════════════════════════")

    wake_api()

    try:
        from telegram_alerts import is_in_season
    except Exception as e:
        log(f"Could not import season gates: {e}")
        return

    for sport in SPORTS:
        if not is_in_season(sport):
            log(f"{sport.upper()}: out of season — skipping")
            continue

        if retry:
            # Only re-check sports that may have had no data at 9 AM
            try:
                r = requests.get(SPORT_ENDPOINTS[sport], timeout=60)
                data = r.json()
                bets = data.get("best_bets", [])
                clean = [b for b in bets if b.get("model_prob", 0) >= 55]
                if clean:
                    log(f"{sport.upper()}: {len(clean)} pick(s) found on retry — sending alerts")
                    run_alerts(sport)
                else:
                    log(f"{sport.upper()}: still no edges on retry — skipping")
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
    parser.add_argument("--retry", action="store_true", help="Noon retry run for missed morning picks")
    args = parser.parse_args()
    run(retry=args.retry)