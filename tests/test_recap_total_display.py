"""
tests/test_recap_total_display.py — Culture & Pulse Analytics
================================================================
Regression test for a display bug fixed in recap_engine.py (2026-09-03):
the daily recap's "Pick: ... -> result" line always showed
r['actual_winner'] (a team name) regardless of market — meaningless for
a total pick, producing lines like "Over 8.5 -> Milwaukee Brewers" (a
team name is not a result for a bet on combined score).

Grading itself (auto_results.score_prediction) was already confirmed
correct — it compares actual_total to the line, not who won — this was
purely a display bug downstream of correct data. Reproduced against
real graded rows: a real "Over 9.0" pick on a Brewers game showed
"Milwaukee Brewers" as the result before this fix.

Usage:
    py tests/test_recap_total_display.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recap_engine import format_result_display


def _check(label, actual, expected):
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label}: got {actual!r}, expected {expected!r}")
    return ok


def run():
    print("Testing recap_engine.format_result_display()...")
    results = []

    # The exact real-world case reported: "Over 9.0 -> Milwaukee Brewers"
    # instead of a final score. Real graded row shape from get_results().
    total_row = {
        "market": "total", "bet": "Over 9.0", "line": 9.0,
        "home_team": "Colorado Rockies", "away_team": "Milwaukee Brewers",
        "home_score": 5, "away_score": 8,
        "actual_winner": "Milwaukee Brewers",
    }
    results.append(_check(
        "total pick shows the final score and combined total, not a team name",
        format_result_display(total_row),
        "Colorado Rockies 5 - 8 Milwaukee Brewers (Total: 13)",
    ))

    # A total row missing scores (shouldn't happen once graded, but must
    # not crash) falls back to actual_winner rather than raising.
    total_row_no_scores = {
        "market": "total", "bet": "Under 44.5", "line": 44.5,
        "home_team": "Team A", "away_team": "Team B",
        "home_score": None, "away_score": None,
        "actual_winner": "Team A",
    }
    results.append(_check(
        "total row with missing scores falls back to actual_winner instead of crashing",
        format_result_display(total_row_no_scores),
        "Team A",
    ))

    # Moneyline/spread rows are unaffected -- still show the winner.
    ml_row = {
        "market": "moneyline", "bet": "Los Angeles Dodgers ML",
        "home_team": "Los Angeles Dodgers", "away_team": "San Francisco Giants",
        "home_score": 6, "away_score": 2,
        "actual_winner": "Los Angeles Dodgers",
    }
    results.append(_check(
        "moneyline pick still shows the winner unchanged",
        format_result_display(ml_row),
        "Los Angeles Dodgers",
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
