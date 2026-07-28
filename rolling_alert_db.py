"""
Rolling performance alert — pulls directly from the live results table
(via database.py's get_conn()) instead of a manual CSV export.

Run it as a step in the same GitHub Actions workflow that runs
score_results / auto_results.py, right after grading finishes.

ASSUMPTIONS ABOUT YOUR SCHEMA (confirm these before trusting output):
    Table: results
    Columns used: date, sport, bet (text of the pick, e.g. "Miami
    Marlins -1.5" or "Over 8.5"), odds_at_pick (American odds, int),
    correct (1 = win, 0 = loss)

If your actual column names differ, edit the SQL in fetch_graded()
and nothing else needs to change.

USAGE:
    python3 rolling_alert_db.py
"""

import os
import sys
import re
from datetime import datetime, timedelta

# Import your existing connection helper — must be run from inside
# the repo (or with the repo on PYTHONPATH) so this import resolves.
try:
    from database import get_conn
except ImportError:
    print("Could not import get_conn from database.py. Run this from "
          "the repo root, or add the repo to PYTHONPATH.")
    sys.exit(1)

# ---- thresholds you can tune ----
ROI_ALERT_PCT = -5.0
WINRATE_ALERT_PCT = 50.0
MIN_SAMPLE = 8
WINDOWS = [7, 14]

# A threshold breach is an alert, not a workflow failure, by default.
# Set FAIL_WORKFLOW_ON_ALERTS=true in the workflow env if you ever
# want a breach to turn the run red again.
FAIL_WORKFLOW_ON_ALERTS = os.getenv("FAIL_WORKFLOW_ON_ALERTS", "false").lower() in ("1", "true", "yes")


def american_to_profit(odds, stake=100):
    odds = float(odds)
    return stake * odds / 100 if odds > 0 else stake * 100 / abs(odds)


def infer_market(bet_text):
    """Best-effort market classifier from the free-text bet field.
    Adjust this if you already store market type as its own column —
    in that case just select it directly in fetch_graded() instead."""
    bet_text = (bet_text or "").strip()
    if re.match(r'^(Over|Under)\b', bet_text, re.IGNORECASE):
        return "Total"
    if re.search(r'[+-]\d+(\.\d+)?$', bet_text):
        return "Spread"
    return "ML"


def fetch_graded(days_back=30):
    """Pull graded results from the last N days."""
    conn = get_conn()
    cur = conn.cursor()
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    cur.execute(
        """
        SELECT r.date, r.sport, p.bet, r.odds_at_pick, r.correct
        FROM results r
        JOIN predictions p ON r.prediction_id = p.id
        WHERE r.date >= ?
          AND r.correct IS NOT NULL
        """,
        (cutoff,),
    )
    rows = cur.fetchall()
    out = []
    for r in rows:
        date, sport, bet, odds, correct = r[0], r[1], r[2], r[3], r[4]
        out.append({
            "date": date,
            "sport": sport,
            "bet": bet,
            "market": infer_market(bet),
            "odds": odds,
            "win": bool(correct),
        })
    return out


def window_stats(rows):
    n = len(rows)
    if n == 0:
        return None
    wins = sum(1 for r in rows if r["win"])
    win_rate = wins / n * 100
    priced = [r for r in rows if r["odds"] is not None]
    skipped = n - len(priced)
    profit = sum(american_to_profit(r["odds"]) if r["win"] else -100 for r in priced)
    roi = profit / (len(priced) * 100) * 100 if priced else None
    return {"n": n, "win_rate": win_rate, "roi": roi, "skipped": skipped}


def check_group(label, rows, as_of, days):
    cutoff = as_of - timedelta(days=days - 1)
    window_rows = [r for r in rows if datetime.strptime(r["date"], "%Y-%m-%d") >= cutoff]
    stats = window_stats(window_rows)
    if stats is None or stats["n"] < MIN_SAMPLE:
        return None, stats
    flags = []
    if stats["roi"] is not None and stats["roi"] < ROI_ALERT_PCT:
        flags.append(f"ROI {stats['roi']:.1f}% < {ROI_ALERT_PCT}%")
    if stats["win_rate"] < WINRATE_ALERT_PCT:
        flags.append(f"win rate {stats['win_rate']:.1f}% < {WINRATE_ALERT_PCT}%")
    return flags, stats


def fmt_stats(label, stats, flags):
    roi_str = f"{stats['roi']:.1f}%" if stats["roi"] is not None else "N/A (no priced picks)"
    tag = " <-- ALERT" if flags else ""
    skip_note = f", skipped={stats['skipped']} (no odds)" if stats.get("skipped") else ""
    return (f"  {label}: n={stats['n']}, win_rate={stats['win_rate']:.1f}%, "
            f"roi={roi_str}{skip_note}{tag}")


def run():
    rows = fetch_graded(days_back=30)
    if not rows:
        print("No graded results found in the last 30 days. Nothing to check.")
        return

    as_of = max(datetime.strptime(r["date"], "%Y-%m-%d") for r in rows)
    print(f"Rolling alert check — as of {as_of.date()}\n")

    any_alert = False
    markets = sorted(set(r["market"] for r in rows))
    sports = sorted(set(r["sport"] for r in rows))

    for days in WINDOWS:
        print(f"=== {days}-day window ===")

        flags, stats = check_group("overall", rows, as_of, days)
        if stats:
            print(fmt_stats("OVERALL", stats, flags))
            if flags:
                any_alert = True
                for f in flags:
                    print(f"    -> {f}")
        else:
            print(f"  OVERALL: not enough graded picks (min {MIN_SAMPLE})")

        for mkt in markets:
            sub = [r for r in rows if r["market"] == mkt]
            flags, stats = check_group(mkt, sub, as_of, days)
            if stats is None:
                continue
            print(fmt_stats(mkt, stats, flags))
            if flags:
                any_alert = True
                for f in flags:
                    print(f"    -> {f}")

        for sport in sports:
            sub = [r for r in rows if r["sport"] == sport]
            flags, stats = check_group(sport, sub, as_of, days)
            if stats is None:
                continue
            print(fmt_stats(f"sport={sport}", stats, flags))
            if flags:
                any_alert = True
                for f in flags:
                    print(f"    -> {f}")

        print()

    if any_alert:
        print("RESULT: one or more windows breached thresholds. Consider reducing "
              "stake size on flagged markets/sports until they recover.")
        # Breach = alert, not a workflow failure, unless explicitly requested.
        if FAIL_WORKFLOW_ON_ALERTS:
            sys.exit(1)
        sys.exit(0)
    else:
        print("RESULT: no thresholds breached.")
        sys.exit(0)


if __name__ == "__main__":
    run()
