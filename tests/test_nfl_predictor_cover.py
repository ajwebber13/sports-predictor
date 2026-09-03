"""
tests/test_nfl_predictor_cover.py — Culture & Pulse Analytics
================================================================
Regression test for the spread cover-probability sign bug fixed in
nfl_predictor.py (2026-09-02): home_cov/away_cov used to be computed as
P(margin > spread_line) instead of P(margin > -spread_line), which is
backwards for any favorite (negative spread_line). Uses an absurd
+/-100 point spread line — no real team is ever within 100 points of
covering or failing to cover — so the correct side is unambiguous
regardless of the two teams' actual projected scores.

Requires DB access for the situational-row lookup (synthetic team names
safely fall through to defaults). The ESPN injury-feed fetch is mocked
out — predict() already treats it as best-effort (wrapped in try/except,
defaults to 0 adjustment on failure), and hitting the real endpoint here
just adds a slow, flaky network dependency to a math regression test.

Usage:
    py tests/test_nfl_predictor_cover.py
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

from nfl_predictor import NFLPredictionEngine
from nfl_data import NFLTeamStats


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


def run():
    print("Testing NFL spread cover-probability sign...")
    results = []

    home = NFLTeamStats(
        team_name="Test Home NFL", team_id="0", wins=9, losses=3,
        home_wins=6, home_losses=1, away_wins=3, away_losses=2,
        pts_per_game=24.5, pts_allowed=20.0, yards_per_play_off=5.8,
        yards_per_play_def=5.2, pass_yards_pg=240.0, rush_yards_pg=120.0,
        turnovers_given=1.0, turnovers_forced=1.2, third_down_pct=0.42,
        sacks_allowed=2.0, sacks_forced=2.5, penalties_pg=5.5,
    )
    away = NFLTeamStats(
        team_name="Test Away NFL", team_id="1", wins=7, losses=5,
        home_wins=4, home_losses=2, away_wins=3, away_losses=3,
        pts_per_game=22.0, pts_allowed=23.5, yards_per_play_off=5.5,
        yards_per_play_def=5.6, pass_yards_pg=225.0, rush_yards_pg=110.0,
        turnovers_given=1.2, turnovers_forced=0.9, third_down_pct=0.39,
        sacks_allowed=2.3, sacks_forced=2.0, penalties_pg=6.0,
    )
    engine = NFLPredictionEngine()

    # get_matchup_injury_adj hits a real ESPN endpoint that's unreliable in
    # some sandboxed network environments — predict() already treats it as
    # best-effort, so mock it out rather than let a network hiccup fail a
    # pure math regression test.
    with patch("nfl_predictor.get_matchup_injury_adj", return_value=(0.0, 0.0)):
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
