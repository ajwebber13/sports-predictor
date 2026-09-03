"""
tests/test_enhanced_predictor_cover.py — Culture & Pulse Analytics
================================================================
Regression test for the spread cover-probability sign bug fixed in
enhanced_predictor.py (2026-09-02): team_a_cover_prob/team_b_cover_prob
used to be computed as P(margin > spread_line) instead of
P(margin > -spread_line), which is backwards for any favorite (negative
spread_line). Uses an absurd +/-100 point spread line — no real team is
ever within 100 points of covering or failing to cover — so the correct
side is unambiguous regardless of the two teams' actual ratings.

Every EnhancedProfile field has a default, so this is fully synthetic
and hermetic — no DB/network dependency (the NFL advanced-metrics and
weather lookups inside predict() are both wrapped in try/except and
league="CFB" here skips the NFL-only DB path entirely).

Usage:
    py tests/test_enhanced_predictor_cover.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enhanced_predictor import EnhancedPredictionEngine
from enhanced_data import EnhancedProfile


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


def run():
    print("Testing enhanced_predictor spread cover-probability sign...")
    results = []

    profile_a = EnhancedProfile(team_name="Test Team A", league="CFB", pts_off=30.0, pts_def=24.0)
    profile_b = EnhancedProfile(team_name="Test Team B", league="CFB", pts_off=27.0, pts_def=27.0)
    engine = EnhancedPredictionEngine()

    # Team A "laying" 100 -- no real team ever covers a 100-point favorite line.
    pred_a_big_favorite = engine.predict(
        profile_a, profile_b, spread_line=-100.0, over_under=55.0,
        odds_a=-150, odds_b=130, a_is_home=True, simulations=20000,
    )
    results.append(_check(
        "team_a cover_prob is near-zero at spread_line=-100",
        pred_a_big_favorite.team_a_cover_prob < 5.0,
        f"team_a_cover_prob={pred_a_big_favorite.team_a_cover_prob}",
    ))
    results.append(_check(
        "team_b cover_prob is near-certain at spread_line=-100",
        pred_a_big_favorite.team_b_cover_prob > 95.0,
        f"team_b_cover_prob={pred_a_big_favorite.team_b_cover_prob}",
    ))

    # Flip it: team A getting +100 -- team A covers almost certainly.
    pred_a_big_dog = engine.predict(
        profile_a, profile_b, spread_line=100.0, over_under=55.0,
        odds_a=-150, odds_b=130, a_is_home=True, simulations=20000,
    )
    results.append(_check(
        "team_a cover_prob is near-certain at spread_line=+100",
        pred_a_big_dog.team_a_cover_prob > 95.0,
        f"team_a_cover_prob={pred_a_big_dog.team_a_cover_prob}",
    ))
    results.append(_check(
        "team_b cover_prob is near-zero at spread_line=+100",
        pred_a_big_dog.team_b_cover_prob < 5.0,
        f"team_b_cover_prob={pred_a_big_dog.team_b_cover_prob}",
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
