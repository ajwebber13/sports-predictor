"""
tests/test_alert_throttle_confidence.py — Culture & Pulse Analytics
================================================================
Regression test for a confidence-flip bug fixed in alert_throttle.py
(2026-09-03): get_confidence() assumed model_prob was always the HOME
team's probability and flipped it (100 - model_prob) whenever the
picked team's name wasn't found in the bet label. That's the exact bug
already fixed in telegram_alerts.get_recommended_prob() weeks earlier —
every route now computes model_prob as the confidence in the actual
recommended pick, for every market — but this second copy of the same
logic was never updated to match.

Worse for "total" bets specifically: the label is "Over 50.5" /
"Under 50.5", which never contains a team name, so bet_on_home was
always False and EVERY total bet's confidence got silently inverted.
Confirmed live: Tulane @ Duke's real Over 50.5 pick (model_prob=71.0,
comfortably above the 65% floor) was being suppressed as 29.0% —
found while re-running the CFB throttle for this week's slate, where
fixing this took the qualified-picks count from 5 to 17 out of 56.

Usage:
    py tests/test_alert_throttle_confidence.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alert_throttle import get_confidence


def _check(label, actual, expected, tol=0.01):
    ok = abs(actual - expected) < tol
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}: got {actual}, expected {expected}")
    return ok


def run():
    print("Testing alert_throttle.get_confidence()...")
    results = []

    # Total bet: label never contains a team name -- must NOT flip.
    results.append(_check(
        "total bet (Over) trusts model_prob directly, no team-name flip",
        get_confidence({"game": "Tulane @ Duke", "bet": "Over 50.5", "model_prob": 71.0}),
        71.0,
    ))
    results.append(_check(
        "total bet (Under) trusts model_prob directly, no team-name flip",
        get_confidence({"game": "Tulane @ Duke", "bet": "Under 50.5", "model_prob": 38.0}),
        38.0,
    ))

    # Spread/moneyline bet on the AWAY team: label doesn't contain the
    # HOME team's name, so the old code would have flipped this too --
    # model_prob already means "confidence in this picked side."
    results.append(_check(
        "away-team spread pick trusts model_prob directly",
        get_confidence({"game": "North Texas @ Indiana", "bet": "North Texas +40.5", "model_prob": 73.2}),
        73.2,
    ))

    # Spread/moneyline bet on the HOME team: happened to already work
    # under the old logic (coincidentally, not by design) -- must still
    # work under the fix.
    results.append(_check(
        "home-team spread pick trusts model_prob directly",
        get_confidence({"game": "Ball State @ Ohio State", "bet": "Ohio State -50.5", "model_prob": 82.3}),
        82.3,
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
