"""
render_job.py — Culture & Pulse Analytics
Runs on Render cron schedule daily.
Fires alerts for all active sports and pulls ESPN results.

No PC required — runs entirely in the cloud.
"""

import os
import sys
import requests
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API_BASE         = "https://sports-predictor-api-44a0.onrender.com"
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"

# Active months per sport
SPORT_SEASONS = {
    "nba":   [1, 2, 3, 4, 5, 6, 10, 11, 12],
    "wnba":  [5, 6, 7, 8, 9, 10],
    "nfl":   [1, 2, 8, 9, 10, 11, 12],
    "ncaaf": [1, 8, 9, 10, 11, 12],
}

SPORT_ENABLED = {
    "nba":   True,
    "wnba":  True,
    "nfl":   False,  # flip to True in August
    "ncaaf": False,  # flip to True in August
}


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] {msg}", flush=True)


def is_in_season(sport: str) -> bool:
    return datetime.now().month in SPORT_SEASONS.get(sport, [])


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
# ─────────────────────────────────────────────────────────────

def run_alerts(sport: str):
    """Hit the API edge endpoint and send Telegram alerts."""
    log(f"Fetching {sport.upper()} edges...")

    try:
        if sport == "wnba":
            r = requests.get(f"{API_BASE}/wnba/edges", timeout=60)
        elif sport == "nba":
            r = requests.get(f"{API_BASE}/nba/edges", timeout=60)
        else:
            r = requests.get(f"{API_BASE}/edges", params={"sport": sport}, timeout=60)

        data = r.json()
    except Exception as e:
        log(f"API error for {sport}: {e}")
        return

    bets = data.get("best_bets", [])

    if not bets:
        log(f"No {sport.upper()} edges found today.")
        send_telegram(
            f"🏀 <b>C&amp;P Edge Report — {sport.upper()}</b>\n\n"
            f"No edges above threshold today. Stay patient."
        )
        return

    # Save predictions locally on Render (ephemeral but useful for same-run results check)
    try:
        from prediction_logger import save_all_predictions
        save_all_predictions(bets, sport)
        log(f"Saved {len(bets)} predictions.")
    except Exception as e:
        log(f"Prediction logger error: {e}")

    # Send alerts via telegram_alerts formatting
    try:
        from telegram_alerts import (
            format_header, format_wnba_alert, format_nba_alert,
            format_football_alert, get_game_times, get_recommended_prob
        )

        game_times = get_game_times(sport)

        # Filter contradictory alerts
        clean_bets = []
        for bet in bets:
            if get_recommended_prob(bet) >= 45:
                clean_bets.append(bet)
            else:
                log(f"Skipping contradictory: {bet.get('game')}")

        if not clean_bets:
            log("All alerts filtered as contradictory.")
            return

        send_telegram(format_header(clean_bets, sport))
        time.sleep(1)

        for bet in clean_bets:
            game      = bet.get("game", "")
            game_time = game_times.get(game, "Time TBD")

            if game_time == "Time TBD":
                parts = game.split(" @ ")
                if len(parts) == 2:
                    game_time = game_times.get(parts[0], game_times.get(parts[1], "Time TBD"))

            if sport == "wnba":
                msg = format_wnba_alert(bet, game_time)
            elif sport == "nba":
                msg = format_nba_alert(bet, game_time)
            else:
                msg = format_football_alert(bet, sport, game_time)

            send_telegram(msg)
            time.sleep(1)

        log(f"Sent {len(clean_bets)} {sport.upper()} alerts.")

    except Exception as e:
        log(f"Alert formatting error: {e}")


# ─────────────────────────────────────────────────────────────
# RESULTS RUNNER
# ─────────────────────────────────────────────────────────────

def run_results():
    """Pull ESPN results and update record."""
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

def run():
    log("══════════════════════════════════════════════")
    log(f"Culture & Pulse — Daily Run — {datetime.now().strftime('%A %B %d, %Y')}")
    log("══════════════════════════════════════════════")

    for sport in SPORT_ENABLED:
        if not SPORT_ENABLED[sport]:
            log(f"{sport.upper()}: disabled")
            continue
        if not is_in_season(sport):
            log(f"{sport.upper()}: out of season")
            continue
        run_alerts(sport)
        time.sleep(2)

    log("")
    run_results()

    log("══════════════════════════════════════════════")
    log("Daily run complete.")
    log("══════════════════════════════════════════════")


if __name__ == "__main__":
    run()