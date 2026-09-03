"""
tests/test_render_job_date_filter.py — Culture & Pulse Analytics
================================================================
Regression test for the "no game time, no send" hard rule added to
render_job.py (2026-09-04), in both the CFB/NFL "original per-bet flow"
and the WNBA/MLB "leaner" path.

Root cause of the incident this fixes: the date filter used to be
`if raw_time and not is_today_ct(raw_time): continue` -- which only
ever checked "is this today" when a real time was already known. When
raw_time was empty (the exact CFB failure mode: get_game_times("cfb")
was silently returning nothing to match against, see
test_cfb_game_times.py), the whole check short-circuited and let the
bet through as if it were today's game. That's how a Saturday CFB
game's alert reached Discord on a Thursday afternoon run -- the date
filter never actually evaluated it. The fix makes an unknown kickoff
time an explicit hold in both paths, never a silent pass-through, and
render_job.run_alerts() also holds at send time if the display game_time
is still "Time TBD" for any other reason -- two independent layers, not
one relying on the other.

Both paths use a real 2026-09-03 (today, per the CFB_CONSTANTS/live
session context) reference date to make is_today_ct comparisons
concrete.

Usage:
    py tests/test_render_job_date_filter.py
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

import render_job
import telegram_alerts


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


def run():
    results = []
    sent = []

    def fake_send_discord_alert(text, sport=None):
        sent.append((sport, text))
        return True

    today_iso = telegram_alerts.get_today_ct().isoformat() + "T18:00:00Z"
    saturday_iso = "2026-09-06T18:00:00Z"  # a real future date relative to "today" in this session

    bets = [
        {"game": "Today Away @ Today Home", "market": "moneyline", "bet": "Today Home ML",
         "model_prob": 90.0, "edge": 0.3, "odds": -150, "pick": "Today Home"},
        {"game": "NoTime Away @ NoTime Home", "market": "moneyline", "bet": "NoTime Home ML",
         "model_prob": 90.0, "edge": 0.3, "odds": -150, "pick": "NoTime Home"},
        {"game": "Future Away @ Future Home", "market": "moneyline", "bet": "Future Home ML",
         "model_prob": 90.0, "edge": 0.3, "odds": -150, "pick": "Future Home"},
    ]

    game_times = {
        "Today Away @ Today Home": "Today's game time",
        # "NoTime Away @ NoTime Home" deliberately absent -- unresolved time
        "Future Away @ Future Home": "Sat Sep 6",
    }
    game_times_raw = {
        "Today Away @ Today Home": today_iso,
        # NoTime game has no raw-time entry either
        "Future Away @ Future Home": saturday_iso,
    }

    print("Testing render_job.run_alerts()'s per-bet flow date filter...")
    with patch.object(render_job, "fetch_edges_with_retry", return_value={"best_bets": bets}), \
         patch.object(render_job, "send_discord_alert", side_effect=fake_send_discord_alert), \
         patch.object(render_job, "already_alerted_today", return_value=False), \
         patch.object(telegram_alerts, "get_game_times", return_value=(game_times, game_times_raw)), \
         patch("services.odds_parser.get_live_odds", return_value=[], create=True), \
         patch("database.log_odds", return_value=None, create=True), \
         patch("database.log_situational_factors", return_value=None, create=True), \
         patch("database.log_prediction", return_value=None, create=True), \
         patch("alert_throttle.throttle_bets", side_effect=lambda bets, sport: (bets, [], "no-op throttle")):
        render_job.run_alerts("cfb")

    sent_games = [render_job_bet for _, render_job_bet in sent]
    results.append(_check(
        "today's game with a known time is sent",
        any("Today Home" in t for t in sent_games),
        f"sent count={len(sent)}",
    ))
    results.append(_check(
        "unknown-time game is held, never sent",
        not any("NoTime" in t for t in sent_games),
        f"sent games mention NoTime: {any('NoTime' in t for t in sent_games)}",
    ))
    results.append(_check(
        "future-day game (known time, not today) is held, never sent",
        not any("Future Home" in t for t in sent_games),
        f"sent games mention Future: {any('Future Home' in t for t in sent_games)}",
    ))
    results.append(_check(
        "exactly one bet survived (today's game only)",
        len(sent) == 1,
        f"sent count={len(sent)}",
    ))

    print("\nTesting the WNBA/MLB leaner path's date filter (same fix, separate code path)...")
    wnba_bets = [
        {"game": "NoTime Away @ NoTime Home", "market": "moneyline", "bet": "NoTime Home ML",
         "model_prob": 90.0, "edge": 0.3, "odds": -150, "pick": "NoTime Home"},
        {"game": "Future Away @ Future Home", "market": "moneyline", "bet": "Future Home ML",
         "model_prob": 90.0, "edge": 0.3, "odds": -150, "pick": "Future Home"},
    ]
    wnba_game_times = {"Future Away @ Future Home": "Sat Sep 6"}
    wnba_game_times_raw = {"Future Away @ Future Home": saturday_iso}

    logged = []
    with patch.object(render_job, "fetch_edges_with_retry", return_value={"best_bets": wnba_bets}), \
         patch.object(render_job, "log", side_effect=lambda msg: logged.append(msg)), \
         patch.object(render_job, "send_discord_alert", side_effect=fake_send_discord_alert), \
         patch.object(telegram_alerts, "get_game_times", return_value=(wnba_game_times, wnba_game_times_raw)), \
         patch("services.odds_parser.get_live_odds", return_value=[], create=True), \
         patch("database.log_odds", return_value=None, create=True), \
         patch("database.log_situational_factors", return_value=None, create=True):
        result = render_job.run_alerts("wnba")

    results.append(_check(
        "leaner path returns False (nothing to send) when every bet is held/stale",
        result is False,
        f"result={result}",
    ))
    results.append(_check(
        "leaner path logs 'held: no game time' for the unknown-time game",
        any("held: no game time" in m and "NoTime" in m for m in logged),
        f"logged={[m for m in logged if 'NoTime' in m or 'held' in m]}",
    ))
    results.append(_check(
        "leaner path logs the future-day game as stale, not held",
        any("Skipping stale game" in m and "Future" in m for m in logged),
        f"logged={[m for m in logged if 'Future' in m]}",
    ))

    print()
    if all(results):
        print(f"All {len(results)} tests passed.")
        return 0
    else:
        failed = len(results) - sum(results)
        print(f"{failed} of {len(results)} tests FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(run())
