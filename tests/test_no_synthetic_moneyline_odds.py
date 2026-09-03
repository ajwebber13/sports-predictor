"""
tests/test_no_synthetic_moneyline_odds.py — Culture & Pulse Analytics
================================================================
Regression test for the "no real price, no bet" rule added 2026-09-02
to routes_cfb.py, routes_nfl.py, and routes_wnba.py: a moneyline bet
whose odds were synthesized from the model's own probability (CFB/NFL)
or never had real odds behind them (WNBA) must never be emitted.

Why this matters: "edge" against a synthesized/placeholder price is
circular — it can only ever measure "the model agrees with itself,"
never a real edge against the market. This is common for CFB
blowout/G5 buy games, where DraftKings/FanDuel either post no h2h
market at all or a price so extreme (e.g. -100000/+5000) it fails the
abs(price) > 2000 sanity filter in get_market_implied() — confirmed on
the real Iowa (-100000) vs Northern Illinois (+5000) game, one of 16
of 33 CFB moneyline bets with no real price in a single week's slate.

Also covers a WNBA-specific bug found while wiring this in:
routes_wnba.py's get_market_implied() fell back to a hardcoded
(-110, -110) instead of (None, None) when no real odds were found —
directly contradicting its own docstring ("never a price synthesized
from the model's own probability") and making a missing price
indistinguishable from a real posted -110.

Usage:
    py tests/test_no_synthetic_moneyline_odds.py
"""

import os
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


# Odds so extreme both sides get filtered by the abs(price) > 2000 guard --
# same shape as the real Iowa/Northern Illinois -100000/+5000 game.
EVENTS_ODDS_FAKE = [{
    "home_team": "BigSchool", "away_team": "TinySchool",
    "bookmakers": [{"markets": [
        {"key": "h2h", "outcomes": [{"name": "BigSchool", "price": -100000}, {"name": "TinySchool", "price": 5000}]},
    ]}],
}]

EVENTS_ODDS_REAL = [{
    "home_team": "BigSchool", "away_team": "TinySchool",
    "bookmakers": [{"markets": [
        {"key": "h2h", "outcomes": [{"name": "BigSchool", "price": -300}, {"name": "TinySchool", "price": 250}]},
    ]}],
}]


def run():
    print("Testing moneyline is dropped whenever odds aren't real...")
    results = []

    pred_football = SimpleNamespace(
        home_win_prob=90.0, away_win_prob=10.0,
        projected_home=35.0, projected_away=10.0, projected_total=45.0,
        home_cover_prob=90.0, away_cover_prob=10.0,
        over_prob=50.0, under_prob=50.0,
        home_record="5-1", away_record="0-6",
        home_rest_days=7, away_rest_days=7,
    )
    pred_wnba = SimpleNamespace(
        home_win_prob=90.0, away_win_prob=10.0,
        projected_home=85.0, projected_away=70.0, projected_total=155.0,
        home_cover_prob=90.0, away_cover_prob=10.0,
        over_prob=50.0, under_prob=50.0,
        home_record="5-1", away_record="0-6",
        home_rest_days=2, away_rest_days=2,
    )

    import app.api.routes_cfb as routes_cfb
    from app.api.routes_cfb import _build_bets_for_game as cfb_build
    from app.api.routes_nfl import _build_bets_for_game as nfl_build
    from app.api.routes_wnba import _build_bets_for_game as wnba_build

    for label, build_fn, pred in [("CFB", cfb_build, pred_football),
                                    ("NFL", nfl_build, pred_football),
                                    ("WNBA", wnba_build, pred_wnba)]:
        # CFB moneyline is globally disabled as of 2026-09-03
        # (CFB_MONEYLINE_ENABLED, routes_cfb.py) pending real 2026 data --
        # the odds_is_real gate underneath it still needs to be proven
        # separately, so this test forces the flag on for CFB only while
        # checking that gate specifically.
        patch_ctx = patch.object(routes_cfb, "CFB_MONEYLINE_ENABLED", True) if label == "CFB" else nullcontext()
        with patch_ctx:
            bets_fake, _ = build_fn("BigSchool", "TinySchool", pred, EVENTS_ODDS_FAKE, min_edge=3.0)
            markets_fake = [b["market"] for b in bets_fake]
            results.append(_check(
                f"{label}: no-real-odds moneyline is dropped",
                "moneyline" not in markets_fake,
                f"markets={markets_fake}",
            ))

            bets_real, _ = build_fn("BigSchool", "TinySchool", pred, EVENTS_ODDS_REAL, min_edge=3.0)
            markets_real = [b["market"] for b in bets_real]
            results.append(_check(
                f"{label}: real-odds moneyline still emitted",
                "moneyline" in markets_real,
                f"markets={markets_real}",
            ))

    # And separately: confirm CFB moneyline is off by default (the flag,
    # not just the odds gate) even with real odds available.
    bets_cfb_default, _ = cfb_build("BigSchool", "TinySchool", pred_football, EVENTS_ODDS_REAL, min_edge=3.0)
    results.append(_check(
        "CFB: moneyline stays off by default (CFB_MONEYLINE_ENABLED = False) even with real odds",
        "moneyline" not in [b["market"] for b in bets_cfb_default],
        f"markets={[b['market'] for b in bets_cfb_default]}",
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
