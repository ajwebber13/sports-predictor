"""
tests/test_performance_tracker.py — Culture & Pulse Analytics
================================================================
Protects the accounting math in performance_tracker.py. These are the
exact cases from the code review: known-good payouts at specific odds,
plus the "missing odds excluded, not fabricated" behavior.

Usage:
    py tests/test_performance_tracker.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from performance_tracker import _american_profit


def _check(label, actual, expected, tol=0.001):
    ok = abs(actual - expected) < tol
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}: got {actual}, expected {expected}")
    return ok


def run():
    print("Testing _american_profit()...")
    results = []

    # -125 win: risk 1 unit, win 100/125 = 0.80 units profit
    results.append(_check("−125 win", _american_profit(-125, won=True), 0.80))

    # +150 win: risk 1 unit, win 150/100 = 1.50 units profit
    results.append(_check("+150 win", _american_profit(150, won=True), 1.50))

    # -110 loss: lose the full 1 unit staked, regardless of odds
    results.append(_check("−110 loss", _american_profit(-110, won=False), -1.00))

    # -110 win: risk 1 unit, win 100/110 = 0.9091 units profit
    results.append(_check("−110 win", _american_profit(-110, won=True), 0.9091, tol=0.001))

    # +200 loss: still just -1 unit regardless of how big the odds were
    results.append(_check("+200 loss", _american_profit(200, won=False), -1.00))

    # missing odds (None) + win: returns 0.0 rather than guessing a payout —
    # calculate_roi() is responsible for excluding these picks entirely
    # from units_risked/profit_units, not this function faking a number
    results.append(_check("missing odds, won=True returns 0.0 (caller excludes, not this fn)",
                           _american_profit(None, won=True), 0.0))

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
