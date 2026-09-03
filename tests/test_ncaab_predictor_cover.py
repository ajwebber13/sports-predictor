"""
tests/test_ncaab_predictor_cover.py — Culture & Pulse Analytics
================================================================
Regression test for the spread cover-probability sign bug fixed in
ncaab_predictor.py (2026-09-02): home_cov/away_cov used to be computed
as P(margin > spread_line) instead of P(margin > -spread_line), which
is backwards for any favorite (negative spread_line). Uses an absurd
+/-100 point spread line — no real team is ever within 100 points of
covering or failing to cover — so the correct side is unambiguous
regardless of the two teams' actual projected scores.

Fully synthetic team stats — ncaab_predictor.predict() has no DB/
network dependency (get_rest_days() returns a safe default for an
unrecognized team name), so this test is hermetic and fast.

Usage:
    py tests/test_ncaab_predictor_cover.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ncaab_predictor import NCAABPredictionEngine
from ncaab_data import NCAABTeamStats


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


def run():
    print("Testing NCAAB spread cover-probability sign...")
    results = []

    home = NCAABTeamStats(
        team_name="Test Home NCAAB", team_id="0", wins=15, losses=5,
        home_wins=9, home_losses=1, away_wins=6, away_losses=4,
        pts_per_game=75.0, opp_pts_per_game=68.0, rebounds_per_game=36.0,
        assists_per_game=15.0, turnovers_per_game=12.0, fg_pct=0.46,
        three_pct=0.35, pace=68.0, off_rating=110.0, def_rating=98.0,
    )
    away = NCAABTeamStats(
        team_name="Test Away NCAAB", team_id="1", wins=12, losses=8,
        home_wins=8, home_losses=2, away_wins=4, away_losses=6,
        pts_per_game=71.0, opp_pts_per_game=70.0, rebounds_per_game=34.0,
        assists_per_game=13.0, turnovers_per_game=13.0, fg_pct=0.44,
        three_pct=0.33, pace=68.0, off_rating=104.0, def_rating=102.0,
    )
    engine = NCAABPredictionEngine()

    # Home "laying" 100 -- no real team ever covers a 100-point favorite line.
    pred_home_big_favorite = engine.predict(home, away, spread_line=-100.0, simulations=20000)
    results.append(_check(
        "home cover_prob is near-zero at spread_line=-100",
        pred_home_big_favorite.home_cover_prob < 5.0,
        f"home_cover_prob={pred_home_big_favorite.home_cover_prob}",
    ))
    results.append(_check(
        "away cover_prob is near-certain at spread_line=-100",
        pred_home_big_favorite.away_cover_prob > 95.0,
        f"away_cover_prob={pred_home_big_favorite.away_cover_prob}",
    ))

    # Flip it: home getting +100 -- home covers almost certainly.
    pred_home_big_dog = engine.predict(home, away, spread_line=100.0, simulations=20000)
    results.append(_check(
        "home cover_prob is near-certain at spread_line=+100",
        pred_home_big_dog.home_cover_prob > 95.0,
        f"home_cover_prob={pred_home_big_dog.home_cover_prob}",
    ))
    results.append(_check(
        "away cover_prob is near-zero at spread_line=+100",
        pred_home_big_dog.away_cover_prob < 5.0,
        f"away_cover_prob={pred_home_big_dog.away_cover_prob}",
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
