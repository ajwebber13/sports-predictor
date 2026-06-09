"""
scheduler.py — Culture & Pulse Analytics
Automated daily runner for all sports predictions + results tracking.

Schedule with Windows Task Scheduler to run once daily.
Handles NBA, WNBA now. CFB and NFL auto-enable in season.

Usage:
  python scheduler.py           # run everything for today
  python scheduler.py alerts    # run alerts only
  python scheduler.py results   # run results tracker only
"""

import os
import sys
import time
import subprocess
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_FILE   = os.path.join(BASE_DIR, "scheduler_log.txt")
PYTHON     = sys.executable

# Alert script
ALERTS_SCRIPT  = os.path.join(BASE_DIR, "telegram_alerts.py")
RESULTS_SCRIPT = os.path.join(BASE_DIR, "results_tracker.py")

# Active months per sport
SPORT_SEASONS = {
    "nba":   [1, 2, 3, 4, 5, 6, 10, 11, 12],
    "wnba":  [5, 6, 7, 8, 9, 10],
    "nfl":   [1, 2, 8, 9, 10, 11, 12],
    "ncaaf": [1, 8, 9, 10, 11, 12],
}

# Flip to True when ready to enable
SPORT_ENABLED = {
    "nba":   True,
    "wnba":  True,
    "nfl":   False,   # enable in August
    "ncaaf": False,   # enable in August
}

# Delay between alert runs (seconds) — avoids Telegram rate limits
ALERT_DELAY = 5


# ─────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────

def log(msg: str):
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def is_in_season(sport: str) -> bool:
    return datetime.now().month in SPORT_SEASONS.get(sport, [])


def is_enabled(sport: str) -> bool:
    return SPORT_ENABLED.get(sport, False)


def run_script(script: str, args: list = []) -> bool:
    """Run a Python script as a subprocess. Returns True if successful."""
    cmd = [PYTHON, script] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=False,
            timeout=120,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log(f"  TIMEOUT: {script} {' '.join(args)}")
        return False
    except Exception as e:
        log(f"  ERROR running {script}: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# RUNNERS
# ─────────────────────────────────────────────────────────────

def run_alerts():
    """Fire alerts for all active, enabled sports."""
    log("─── ALERTS ───────────────────────────────────────")
    ran_any = False

    for sport, enabled in SPORT_ENABLED.items():
        if not enabled:
            log(f"  {sport.upper()}: disabled — skipping")
            continue
        if not is_in_season(sport):
            log(f"  {sport.upper()}: out of season — skipping")
            continue

        log(f"  {sport.upper()}: running alerts...")
        success = run_script(ALERTS_SCRIPT, ["--sport", sport])

        if success:
            log(f"  {sport.upper()}: alerts sent ✅")
        else:
            log(f"  {sport.upper()}: alerts failed ❌")

        ran_any = True
        time.sleep(ALERT_DELAY)

    if not ran_any:
        log("  No active sports today.")


def run_results():
    """Pull ESPN results and update the record."""
    log("─── RESULTS TRACKER ──────────────────────────────")
    log("  Pulling ESPN results...")
    success = run_script(RESULTS_SCRIPT)
    if success:
        log("  Results updated ✅")
    else:
        log("  Results update failed ❌")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run():
    log("══════════════════════════════════════════════════")
    log(f"  Culture & Pulse Scheduler — {datetime.now().strftime('%A %B %d, %Y')}")
    log("══════════════════════════════════════════════════")

    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    if cmd == "alerts":
        run_alerts()
    elif cmd == "results":
        run_results()
    else:
        # Full daily run: alerts first, then results
        run_alerts()
        log("")
        run_results()

    log("══════════════════════════════════════════════════")
    log("  Daily run complete.")
    log("══════════════════════════════════════════════════\n")


if __name__ == "__main__":
    run()