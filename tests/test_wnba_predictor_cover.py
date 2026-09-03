"""
tests/test_wnba_predictor_cover.py — Culture & Pulse Analytics
================================================================
Regression test for the spread cover-probability sign bug fixed in
wnba_predictor.py (2026-09-02): home_cov/away_cov used to be computed
as P(margin > spread_line) instead of P(margin > -spread_line), which
is backwards for any favorite (negative spread_line). Uses an absurd
+/-100 point spread line — no real team is ever within 100 points of
covering or failing to cover — so the correct side is unambiguous
regardless of the two teams' actual projected scores.

Requires DB access (same as wnba_predictor.py's own __main__
self-check) — synthetic team names fall through to safe defaults for
situational lookups; injury/line-movement lookups are wrapped in
try/except and default to 0 either way.

Usage:
    py tests/test_wnba_predictor_cover.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

from wnba_predictor import WNBAPredictionEngine
from wnba_data import WNBATeamStats


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


def run():
    print("Testing WNBA spread cover-probability sign...")
    results = []

    home = WNBATeamStats(
        team_name="Test Home WNBA", team_id="0", wins=18, losses=6,
        home_wins=11, home_losses=2, away_wins=7, away_losses=4,
        pts_per_game=85.0, opp_pts_per_game=78.0, rebounds_per_game=34.0,
        assists_per_game=20.0, turnovers_per_game=13.0, fg_pct=0.46,
        three_pct=0.35, pace=82.0, off_rating=104.0, def_rating=95.0,
    )
    away = WNBATeamStats(
        team_name="Test Away WNBA", team_id="1", wins=13, losses=11,
        home_wins=8, home_losses=4, away_wins=5, away_losses=7,
        pts_per_game=80.0, opp_pts_per_game=79.0, rebounds_per_game=32.0,
        assists_per_game=17.0, turnovers_per_game=14.0, fg_pct=0.44,
        three_pct=0.33, pace=81.0, off_rating=99.0, def_rating=98.0,
    )
    engine = WNBAPredictionEngine()

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
