"""
tests/test_recap_result_display.py — Culture & Pulse Analytics
================================================================
Regression tests for two display bugs fixed in recap_engine.py
(2026-09-03), plus a sports-list sync check:

1. The daily recap's "Pick: ... -> result" line always showed
   r['actual_winner'] (a team name) regardless of market — meaningless
   for a total pick, producing lines like "Over 8.5 -> Milwaukee
   Brewers" (a team name is not a result for a bet on combined score).
   Grading itself (auto_results.score_prediction) was already confirmed
   correct — it compares actual_total to the line, not who won — this
   was purely a display bug downstream of correct data.

2. Spread got the same treatment: "Auburn -7.5 -> Baylor" (the
   actual_winner) reads as a loss even when Auburn won by 11 and
   covered comfortably. Now shows the real final score, winner-first,
   regardless of which side was picked — a backdoor cover means the
   picked team can lose outright and still win the bet, so the score
   line has to describe the real game, not imply the pick's outcome.

3. recap_engine.SPORTS used to be its own hardcoded list, independent
   of render_job.ALL_SPORTS — a sport shelved there (nba/ncaab/mlb are
   "temporarily disabled") kept getting its own daily/weekly recap
   anyway from whatever historical results already existed. SPORTS is
   now imported directly from render_job.ALL_SPORTS.

Usage:
    py tests/test_recap_result_display.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from recap_engine import format_result_display, SPORTS
from render_job import ALL_SPORTS


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

    # The requested example: home team favored, wins outright, covers.
    spread_row_home_favorite_covers = {
        "market": "spread", "bet": "Auburn -7.5", "line": -7.5,
        "home_team": "Auburn", "away_team": "Baylor",
        "home_score": 31, "away_score": 20,
        "actual_winner": "Auburn",
    }
    results.append(_check(
        "spread pick shows the final score and margin, winner first",
        format_result_display(spread_row_home_favorite_covers),
        "Auburn 31 - 20 Baylor (won by 11)",
    ))

    # Backdoor cover: the picked (favored) team LOSES outright but the
    # display must still describe the real game accurately -- it should
    # never claim the picked team "won" just because they were picked.
    spread_row_backdoor = {
        "market": "spread", "bet": "Atlanta Braves -1.5", "line": -1.5,
        "home_team": "San Diego Padres", "away_team": "Atlanta Braves",
        "home_score": 8, "away_score": 3,
        "actual_winner": "San Diego Padres",
    }
    results.append(_check(
        "spread pick on the losing side still shows the true winner and margin",
        format_result_display(spread_row_backdoor),
        "San Diego Padres 8 - 3 Atlanta Braves (won by 5)",
    ))

    # Tied game must not crash on a zero margin.
    spread_row_tied = {
        "market": "spread", "bet": "Some Team +3.0", "line": 3.0,
        "home_team": "Home Team", "away_team": "Away Team",
        "home_score": 20, "away_score": 20,
        "actual_winner": "",
    }
    results.append(_check(
        "tied game doesn't crash and reports the tie instead of a fake winner",
        format_result_display(spread_row_tied),
        "Home Team 20 - 20 Away Team (tied)",
    ))

    # Moneyline is unaffected -- still shows the winner.
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

    print("\nTesting recap_engine.SPORTS is synced with render_job.ALL_SPORTS...")
    results.append(_check(
        "recap_engine.SPORTS is exactly render_job.ALL_SPORTS (no independent hardcoded list)",
        SPORTS,
        ALL_SPORTS,
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
