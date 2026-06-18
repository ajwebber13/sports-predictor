"""
run_daily.py — Culture & Pulse Analytics
Daily auto-runner for all leagues.

Automatically skips leagues that are out of season.
Schedule once with Windows Task Scheduler — it handles the rest.

Usage:
  python run_daily.py           # run all active leagues
  python run_daily.py nba       # force NBA only
  python run_daily.py wnba      # force WNBA only
  python run_daily.py nfl       # force NFL only
  python run_daily.py cfb       # force CFB only
"""

import sys
import os
from datetime import datetime

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DEFAULT_STAKE = 100.0

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_log.txt")

# Active months per league
# NBA:  Regular season Oct–Apr, Playoffs Apr–Jun
# WNBA: Regular season May–Sep, Playoffs Sep–Oct
# NFL:  Preseason Aug, Regular Sep–Jan, Playoffs Jan, Super Bowl Feb
# CFB:  Preseason Aug, Regular Aug–Dec, Bowls Dec–Jan
SPORT_ACTIVE_MONTHS = {
    "NBA":          [1, 2, 3, 4, 5, 6, 10, 11, 12],
    "WNBA":         [5, 6, 7, 8, 9, 10],
    "NFL":          [1, 2, 8, 9, 10, 11, 12],
    "CFB":          [1, 8, 9, 10, 11, 12],
    "HBCU_FB":      [8, 9, 10, 11],
    "HBCU_MBB":     [11, 12, 1, 2, 3],
    "HBCU_WBB":     [11, 12, 1, 2, 3],
}

# All supported leagues
ALL_LEAGUES = ["NBA", "WNBA", "NFL", "CFB", "HBCU_FB", "HBCU_MBB", "HBCU_WBB"]
ENABLED_LEAGUES = ["WNBA", "HBCU_FB", "HBCU_MBB", "HBCU_WBB"]
# Leagues with working runners right now
# NFL and CFB re-enable once debug session is done
ENABLED_LEAGUES = ["WNBA"]


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def is_in_season(league: str) -> bool:
    month = datetime.now().month
    return month in SPORT_ACTIVE_MONTHS.get(league, [])


def run_nba(stake: float):
    from nba_wnba_predict import run_league
    from telegram_connector import send_predictions
    predictions = run_league("NBA", stake=stake)
    if predictions:
        send_predictions(predictions, "NBA", bet_it_only=False)


def run_wnba(stake: float):
    from nba_wnba_predict import run_league
    from telegram_connector import send_predictions
    predictions = run_league("WNBA", stake=stake)
    if predictions:
        send_predictions(predictions, "WNBA", bet_it_only=False)


def run_nfl(stake: float):
    # Uncomment after NFL/CFB debug session
    # from auto_predict import run_nfl as _run_nfl
    # _run_nfl(week="auto")
    log("NFL runner not yet enabled — pending debug session.")


def run_cfb(stake: float):
    # Uncomment after NFL/CFB debug session
    # from auto_predict import run_cfb as _run_cfb
    # _run_cfb(week="auto")
    log("CFB runner not yet enabled — pending debug session.")

def run_hbcu_fb(stake: float):
    from hbcu_predict import run_hbcu_sport
    run_hbcu_sport("hbcu_football", send_telegram=True)

def run_hbcu_mbb(stake: float):
    from hbcu_predict import run_hbcu_sport
    run_hbcu_sport("hbcu_mbb", send_telegram=True)

def run_hbcu_wbb(stake: float):
    from hbcu_predict import run_hbcu_sport
    run_hbcu_sport("hbcu_wbb", send_telegram=True)
RUNNERS = {
    "NBA":      run_nba,
    "WNBA":     run_wnba,
    "NFL":      run_nfl,
    "CFB":      run_cfb,
    "HBCU_FB":  run_hbcu_fb,
    "HBCU_MBB": run_hbcu_mbb,
    "HBCU_WBB": run_hbcu_wbb,
}


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    current_month = datetime.now().strftime("%B")
    log(f"Daily run started — {current_month}")

    # If a specific league was passed, force run it
    if len(sys.argv) > 1:
        forced = sys.argv[1].upper()
        if forced in ALL_LEAGUES:
            log(f"Force running {forced}...")
            RUNNERS[forced](DEFAULT_STAKE)
            log(f"{forced} complete.")
            return
        else:
            log(f"Unknown league: {forced}. Options: {', '.join(ALL_LEAGUES)}")
            return

    # Auto mode — run all enabled leagues that are in season
    ran_any = False
    for league in ENABLED_LEAGUES:
        if is_in_season(league):
            log(f"Running {league} (in season)...")
            try:
                RUNNERS[league](DEFAULT_STAKE)
                log(f"{league} complete.")
                ran_any = True
            except Exception as e:
                log(f"ERROR running {league}: {e}")
        else:
            log(f"Skipping {league} (out of season).")

    # Log disabled leagues
    for league in ALL_LEAGUES:
        if league not in ENABLED_LEAGUES:
            if is_in_season(league):
                log(f"Skipping {league} (runner pending debug session).")

    if not ran_any:
        log("No active leagues today. Nothing to run.")

    log("Daily run complete.")


if __name__ == "__main__":
    run()
