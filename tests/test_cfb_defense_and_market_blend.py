"""
tests/test_cfb_defense_and_market_blend.py — Culture & Pulse Analytics
================================================================
Regression tests for three 2026-09-02 fixes to cfb_predictor.py's
projection quality, made after every CFB pick came back as a lopsided
underdog (Ball State over Ohio State, East Carolina over Alabama,
Tulsa ML +425 at 66%) with every projected score in the high teens:

1. cfb_data.py now derives real points-allowed per team from completed
   games in /teams/{id}/schedule (ESPN's /statistics endpoint has no
   points-allowed field at all), replacing the flat 28.0 default that
   made every team's defense look identical.

2. cfb_predictor.py's predict() now accepts market_spread and blends
   the model's own margin 50/50 with the market's implied margin
   before simulating, as a strength-of-schedule/roster-quality prior.
   (elo_ratings only has 6 CFB teams with any real history right now —
   everyone else is the neutral 1500 base — and ranking_engine's CFB
   efficiency component has no data source wired up, so neither is
   usable yet; the market line is the best prior available until real
   2026 results exist to fit on.)

3. routes_cfb.py suppresses the moneyline and spread bets for a game
   when |projected_margin + spread_line| > 17 — a model disagreeing
   with a real posted line by three touchdowns is a data problem, not
   an edge.

Usage:
    py tests/test_cfb_defense_and_market_blend.py
"""

import os
import sys
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


def run():
    results = []

    # ---- 1. Real points-allowed from the schedule ----
    print("Testing cfb_data._get_scoring_from_schedule()...")
    import cfb_data

    fake_schedule = {
        "events": [
            {"competitions": [{"competitors": [
                {"team": {"id": "61"}, "homeAway": "home", "score": {"value": 45.0}},
                {"team": {"id": "276"}, "homeAway": "away", "score": {"value": 7.0}},
            ]}]},
            {"competitions": [{"competitors": [
                {"team": {"id": "2633"}, "homeAway": "home", "score": {"value": 41.0}},
                {"team": {"id": "61"}, "homeAway": "away", "score": {"value": 44.0}},
            ]}]},
            # Unplayed future game -- no score yet, must be skipped, not crash.
            {"competitions": [{"competitors": [
                {"team": {"id": "61"}, "homeAway": "home", "score": {}},
                {"team": {"id": "999"}, "homeAway": "away", "score": {}},
            ]}]},
        ]
    }
    with patch.object(cfb_data, "_get", return_value=fake_schedule):
        scored, allowed, games = cfb_data._get_scoring_from_schedule("61", season=2025)
    # Georgia (id 61) scored 45 and 44 -> avg 44.5; allowed 7 and 41 -> avg 24.0
    results.append(_check(
        "schedule-derived pts_allowed averages the real opponent scores",
        games == 2 and abs(allowed - 24.0) < 0.01,
        f"games={games}, allowed={allowed} (expected games=2, allowed=24.0)",
    ))
    results.append(_check(
        "schedule-derived pts_scored averages this team's own real scores",
        abs(scored - 44.5) < 0.01,
        f"scored={scored} (expected 44.5)",
    ))

    with patch.object(cfb_data, "_get", return_value={"events": []}):
        scored_none, allowed_none, games_none = cfb_data._get_scoring_from_schedule("61", season=2025)
    results.append(_check(
        "no completed games returns (None, None, 0), not a crash or a fake number",
        scored_none is None and allowed_none is None and games_none == 0,
        f"scored={scored_none}, allowed={allowed_none}, games={games_none}",
    ))

    # ---- 2. Market-spread blend in cfb_predictor.predict() ----
    print("\nTesting cfb_predictor market_spread blend...")
    from cfb_predictor import CFBPredictionEngine
    from cfb_data import CFBTeamStats

    strong = CFBTeamStats(
        team_name="Strong", team_id="1", wins=6, losses=0, home_wins=3, home_losses=0,
        away_wins=3, away_losses=0, pts_per_game=38.0, pts_allowed=14.0,
        yards_per_play_off=6.5, yards_per_play_def=4.5, pass_yards_pg=260.0,
        rush_yards_pg=200.0, turnovers_given=0.8, turnovers_forced=1.8,
        third_down_pct=48.0, sacks_allowed=1.2, sacks_forced=3.0, penalties_pg=5.0,
    )
    weak = CFBTeamStats(
        team_name="Weak", team_id="2", wins=1, losses=5, home_wins=1, home_losses=2,
        away_wins=0, away_losses=3, pts_per_game=17.0, pts_allowed=32.0,
        yards_per_play_off=4.8, yards_per_play_def=6.3, pass_yards_pg=180.0,
        rush_yards_pg=100.0, turnovers_given=2.0, turnovers_forced=0.8,
        third_down_pct=32.0, sacks_allowed=3.0, sacks_forced=1.0, penalties_pg=6.5,
    )
    engine = CFBPredictionEngine()

    no_blend = engine.predict(home_stats=strong, away_stats=weak, spread_line=-40.0,
                               over_under=52.0, simulations=20000)
    margin_no_blend = no_blend.projected_home - no_blend.projected_away

    blended = engine.predict(home_stats=strong, away_stats=weak, spread_line=-40.0,
                              over_under=52.0, simulations=20000, market_spread=-40.0)
    margin_blended = blended.projected_home - blended.projected_away

    results.append(_check(
        "market_spread blend pulls the margin toward the market's implied margin",
        margin_blended > margin_no_blend + 3,
        f"no_blend margin={margin_no_blend:.1f}, blended margin={margin_blended:.1f} "
        f"(market implies +40, blended should sit meaningfully above the unblended model)",
    ))

    no_market = engine.predict(home_stats=strong, away_stats=weak, spread_line=0.0,
                                over_under=52.0, simulations=20000, market_spread=None)
    margin_no_market = no_market.projected_home - no_market.projected_away
    results.append(_check(
        "market_spread=None leaves the model's own margin untouched (no fake 0-line blend)",
        abs(margin_no_market - margin_no_blend) < 3,
        f"margin_no_market={margin_no_market:.1f}, margin_no_blend={margin_no_blend:.1f} "
        f"(should be close -- neither used a market prior)",
    ))

    # ---- 3. Sanity gate in routes_cfb.py ----
    print("\nTesting routes_cfb.py sanity gate...")
    from app.api.routes_cfb import _build_bets_for_game

    events_odds = [{
        "home_team": "BigFavorite", "away_team": "BigDog",
        "bookmakers": [{"markets": [
            {"key": "h2h", "outcomes": [{"name": "BigFavorite", "price": -1500}, {"name": "BigDog", "price": 800}]},
            {"key": "spreads", "outcomes": [
                {"name": "BigFavorite", "price": -110, "point": -40.0},
                {"name": "BigDog", "price": -110, "point": 40.0},
            ]},
        ]}],
    }]

    pred_bad = SimpleNamespace(
        home_win_prob=60.0, away_win_prob=40.0,
        projected_home=24.0, projected_away=21.0, projected_total=45.0,  # margin +3, market wants +40
        home_cover_prob=20.0, away_cover_prob=80.0,
        over_prob=50.0, under_prob=50.0,
        home_record="5-1", away_record="1-5",
        home_rest_days=7, away_rest_days=7,
    )
    bets_bad, _ = _build_bets_for_game("BigFavorite", "BigDog", pred_bad, events_odds, min_edge=3.0)
    markets_bad = [b["market"] for b in bets_bad]
    results.append(_check(
        "37pt model/market disagreement suppresses moneyline and spread",
        "moneyline" not in markets_bad and "spread" not in markets_bad,
        f"markets={markets_bad}",
    ))

    pred_ok = SimpleNamespace(
        home_win_prob=95.0, away_win_prob=5.0,
        projected_home=42.0, projected_away=12.0, projected_total=54.0,  # margin +30, market wants +40
        home_cover_prob=35.0, away_cover_prob=65.0,
        over_prob=50.0, under_prob=50.0,
        home_record="6-0", away_record="0-6",
        home_rest_days=7, away_rest_days=7,
    )
    bets_ok, _ = _build_bets_for_game("BigFavorite", "BigDog", pred_ok, events_odds, min_edge=3.0)
    markets_ok = [b["market"] for b in bets_ok]
    results.append(_check(
        "10pt disagreement (within the 17pt gate) still emits bets",
        "moneyline" in markets_ok or "spread" in markets_ok,
        f"markets={markets_ok}",
    ))

    # Real boundary case found live: Ohio State -50.5 vs Ball State, model's
    # blended margin +33.5 -> disagreement = |33.5 + (-50.5)| = 17.0, which
    # is NOT > 17, so the margin-disagreement gate alone lets it through --
    # yet it still simulates to 88% for Ball State covering. The separate
    # spread_prob <= 85 cap exists specifically to catch this.
    events_odds_boundary = [{
        "home_team": "BigFavorite", "away_team": "BigDog",
        "bookmakers": [{"markets": [
            {"key": "h2h", "outcomes": [{"name": "BigFavorite", "price": -1500}, {"name": "BigDog", "price": 800}]},
            {"key": "spreads", "outcomes": [
                {"name": "BigFavorite", "price": -110, "point": -50.5},
                {"name": "BigDog", "price": -110, "point": 50.5},
            ]},
        ]}],
    }]
    pred_boundary = SimpleNamespace(
        home_win_prob=99.0, away_win_prob=1.0,
        projected_home=40.3, projected_away=6.8, projected_total=47.1,  # margin +33.5
        home_cover_prob=11.8, away_cover_prob=88.2,
        over_prob=50.0, under_prob=50.0,
        home_record="6-0", away_record="0-6",
        home_rest_days=7, away_rest_days=7,
    )
    bets_boundary, _ = _build_bets_for_game("BigFavorite", "BigDog", pred_boundary, events_odds_boundary, min_edge=3.0)
    markets_boundary = [b["market"] for b in bets_boundary]
    results.append(_check(
        "88% spread cover prob is suppressed even though margin disagreement is exactly 17.0 (not > 17)",
        "spread" not in markets_boundary,
        f"markets={markets_boundary}",
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
