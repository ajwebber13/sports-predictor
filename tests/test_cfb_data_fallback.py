"""
tests/test_cfb_data_fallback.py — Culture & Pulse Analytics
================================================================
Regression tests for two bugs fixed in cfb_data.py (2026-09-02) that
combined to make cfb_predictor.py project ~16-20 points per team for
every game (real CFB average is ~28) with every record showing 0-0:

1. _fetch_and_parse() blindly preferred ESPN's `perGameValue` field
   over `value` for every stat. For "totalPointsPerGame" specifically,
   ESPN's own perGameValue is garbage (confirmed on Georgia's real
   2024 season: value=32.6, matching totalPoints/gamesPlayed, but
   perGameValue=7.1) while `value` is already the correct per-game
   number. Every team's real ~28-35 ppg was being read as ~5-9.

2. get_team_stats()'s fallback to last season's stats computed
   `last_year = year if month >= 8 else year - 1`. That fallback only
   ever runs when the current season has zero games recorded, which
   by definition means the season labeled by the current calendar
   year hasn't happened yet — so the correct prior season is always
   `year - 1`, regardless of month. The old logic requested the
   SAME (empty) season in September and later, 404'd, and silently
   fell back to `current`'s near-empty stub stats instead of real
   prior-season data.

Usage:
    py tests/test_cfb_data_fallback.py
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cfb_data
from cfb_data import CFBTeamStats


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


def _fake_stats_response(total_points_per_game, games_played=14):
    """Mimics the ESPN /statistics response shape closely enough for
    _fetch_and_parse to parse it — including the real observed quirk
    where totalPointsPerGame's perGameValue is wrong but value is right."""
    return {
        "results": {"stats": {"categories": [
            {"name": "scoring", "stats": [
                {"name": "totalPoints", "value": total_points_per_game * games_played},
                {"name": "totalPointsPerGame", "value": total_points_per_game,
                 "perGameValue": total_points_per_game / games_played},  # the garbage ESPN actually returns
            ]},
            {"name": "general", "stats": [
                {"name": "gamesPlayed", "value": games_played},
            ]},
        ]}}
    }


def _fake_team_response(wins=0, losses=0):
    return {"team": {"record": {"items": [
        {"type": "total", "stats": [{"name": "wins", "value": wins}, {"name": "losses", "value": losses}]},
    ]}}}


def run():
    print("Testing cfb_data.py prior-season fallback...")
    results = []

    # ── Bug 1: totalPointsPerGame parsing ──
    with patch.object(cfb_data, "_get") as mock_get:
        mock_get.side_effect = [
            _fake_stats_response(total_points_per_game=32.6),
            _fake_team_response(wins=0, losses=0),
        ]
        parsed = cfb_data._fetch_and_parse("Test Team", "999", season=2025)
    results.append(_check(
        "totalPointsPerGame uses ESPN's `value`, not the garbage `perGameValue`",
        parsed is not None and abs(parsed.pts_per_game - 32.6) < 0.1,
        f"pts_per_game={parsed.pts_per_game if parsed else None} (expected ~32.6, "
        f"old code would have read ~2.3)",
    ))

    # ── Bug 2: last_year selection in get_team_stats() ──
    real_prior = CFBTeamStats(
        team_name="Test Team", team_id="999", wins=11, losses=2,
        home_wins=6, home_losses=1, away_wins=5, away_losses=1,
        pts_per_game=34.0, pts_allowed=18.0, yards_per_play_off=6.5,
        yards_per_play_def=4.8, pass_yards_pg=260.0, rush_yards_pg=190.0,
        turnovers_given=1.0, turnovers_forced=1.8, third_down_pct=45.0,
        sacks_allowed=1.5, sacks_forced=3.0, penalties_pg=5.0,
    )

    def fake_fetch(team_name, team_id, season=None):
        if season is None:
            # "current" season: no games played yet (preseason)
            return CFBTeamStats(
                team_name=team_name, team_id=team_id, wins=0, losses=0,
                home_wins=0, home_losses=0, away_wins=0, away_losses=0,
                pts_per_game=7.3, pts_allowed=28.0, yards_per_play_off=5.5,
                yards_per_play_def=5.5, pass_yards_pg=16.9, rush_yards_pg=14.0,
                turnovers_given=1.38, turnovers_forced=0.31, third_down_pct=40.0,
                sacks_allowed=0.11, sacks_forced=0.11, penalties_pg=0.0,
            )
        # season is passed explicitly -- the "prior" lookup. The old bug
        # requested the wrong (current, still-empty) year here and got a
        # 404 -> None; the fix always asks for year - 1, which succeeds.
        from datetime import datetime
        if season == datetime.now().year - 1:
            return real_prior
        return None  # simulates a 404 for the wrong year

    with patch.object(cfb_data, "FBS_TEAM_IDS", {"Test Team": "999"}), \
         patch.object(cfb_data, "_fetch_and_parse", side_effect=fake_fetch):
        result = cfb_data.get_team_stats("Test Team")

    results.append(_check(
        "prior-season fallback finds real data instead of falling through to the empty stub",
        result is not None and abs(result.pts_per_game - 34.0) < 0.01,
        f"pts_per_game={result.pts_per_game if result else None} (expected 34.0 from real prior "
        f"season, old code got a 404 on the wrong year and kept the stub's 7.3)",
    ))
    results.append(_check(
        "current-season record is still correctly reported as 0-0 (no games played yet)",
        result is not None and result.wins == 0 and result.losses == 0,
        f"wins={result.wins if result else None}, losses={result.losses if result else None}",
    ))

    # ── Records populate once real games exist this season ──
    def fake_fetch_midseason(team_name, team_id, season=None):
        if season is None:
            return CFBTeamStats(
                team_name=team_name, team_id=team_id, wins=3, losses=1,
                home_wins=2, home_losses=0, away_wins=1, away_losses=1,
                pts_per_game=30.0, pts_allowed=21.0, yards_per_play_off=6.0,
                yards_per_play_def=5.0, pass_yards_pg=230.0, rush_yards_pg=170.0,
                turnovers_given=1.2, turnovers_forced=1.5, third_down_pct=42.0,
                sacks_allowed=1.8, sacks_forced=2.5, penalties_pg=5.5,
            )
        raise AssertionError("should not need the prior-season fallback once current has games")

    with patch.object(cfb_data, "FBS_TEAM_IDS", {"Test Team": "999"}), \
         patch.object(cfb_data, "_fetch_and_parse", side_effect=fake_fetch_midseason):
        midseason = cfb_data.get_team_stats("Test Team")

    results.append(_check(
        "real record populates once Week 1+ results exist this season",
        midseason is not None and midseason.wins == 3 and midseason.losses == 1,
        f"wins={midseason.wins if midseason else None}, losses={midseason.losses if midseason else None}",
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
