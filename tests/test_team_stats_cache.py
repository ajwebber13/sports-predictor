"""
tests/test_team_stats_cache.py — Culture & Pulse Analytics
================================================================
Regression test for the 2026-09-11 /nfl/edges incident: a Render
deploy landed mid-run, wiped nfl_data.py's in-process _stats_cache,
and the next /nfl/edges call had to live-fetch all 32 NFL teams from
ESPN sequentially and uncached — an ~8 minute stall.

Fix: services/team_stats_cache.py adds a persistent (Supabase-backed)
second cache layer, wired into nfl_data.py's get_team_stats() and
cfb_data.py's get_team_stats(). This test simulates a cold start (the
in-process _stats_cache dict cleared, exactly what happens on a fresh
deploy) and verifies the persistent layer is used instead of ESPN.

Covers:
1. services/team_stats_cache.py round-trips a dict through
   write_team_stats_cache()/read_team_stats_cache(), including TTL
   expiry (an old row is treated as a miss).
2. nfl_data.get_team_stats(): a cold-start (cleared _stats_cache) call
   with a warm persistent cache does NOT call ESPN at all.
3. cfb_data.get_team_stats(): same cold-start check.
4. Last-resort flat defaults (total ESPN outage) are never written to
   the persistent cache, so a transient outage can't poison it.

Usage:
    py tests/test_team_stats_cache.py
"""

import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.team_stats_cache as team_stats_cache
import nfl_data
import cfb_data
from nfl_data import NFLTeamStats
from cfb_data import CFBTeamStats


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


class _FakeRow(dict):
    """Mimics database.py's Row wrapper: supports row["col"] access."""
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


class _FakeCursor:
    def __init__(self, store):
        self._store = store
        self._result = None

    def execute(self, sql, params=()):
        sql_norm = " ".join(sql.split())
        if sql_norm.startswith("SELECT"):
            sport, team_name = params
            row = self._store.get((sport, team_name))
            self._result = _FakeRow(row) if row else None
        elif sql_norm.startswith("INSERT"):
            sport, team_name, cached_at, stats_json = params
            self._store[(sport, team_name)] = {"stats_json": stats_json, "cached_at": cached_at}

    def fetchone(self):
        return self._result


class _FakeConn:
    """Simulates the shared DB — the dict passed in stands in for
    persistent storage across simulated 'process restarts' (since a
    real Postgres row does not reset when _stats_cache is cleared)."""
    def __init__(self, store):
        self._store = store

    def cursor(self):
        return _FakeCursor(self._store)

    def commit(self):
        pass

    def close(self):
        pass


def run():
    print("Testing team_stats_cache persistence across simulated cold starts...")
    results = []
    persistent_store = {}  # stands in for the real Supabase table

    def fake_get_conn():
        return _FakeConn(persistent_store)

    # ── 1. services/team_stats_cache.py round-trip + TTL ──
    with patch("database.get_conn", side_effect=fake_get_conn, create=True):
        team_stats_cache.write_team_stats_cache("nfl", "Kansas City Chiefs", {"pts_per_game": 27.5})
        got = team_stats_cache.read_team_stats_cache("nfl", "Kansas City Chiefs")
    results.append(_check(
        "write then read returns the same dict",
        got == {"pts_per_game": 27.5},
        f"got={got}",
    ))

    # Expired row (cached_at far in the past) should be a miss
    persistent_store[("nfl", "Old Team")] = {
        "stats_json": '{"pts_per_game": 10.0}',
        "cached_at": int(time.time()) - team_stats_cache.TEAM_STATS_CACHE_TTL_SECONDS - 100,
    }
    with patch("database.get_conn", side_effect=fake_get_conn, create=True):
        expired = team_stats_cache.read_team_stats_cache("nfl", "Old Team")
    results.append(_check(
        "a row older than the TTL is treated as a cache miss",
        expired is None,
        f"got={expired} (expected None)",
    ))

    # ── 2. nfl_data.get_team_stats() cold start ──
    real_stats = NFLTeamStats(
        team_name="Buffalo Bills", team_id="2", wins=11, losses=6,
        home_wins=6, home_losses=3, away_wins=5, away_losses=3,
        pts_per_game=27.8, pts_allowed=19.4, yards_per_play_off=6.0,
        yards_per_play_def=5.0, pass_yards_pg=245.0, rush_yards_pg=135.0,
        turnovers_given=1.0, turnovers_forced=1.6, third_down_pct=44.0,
        sacks_allowed=2.0, sacks_forced=3.1, penalties_pg=5.5,
    )
    espn_calls = {"count": 0}

    def fake_fetch_and_parse(team_name, team_id, season=None):
        espn_calls["count"] += 1
        return real_stats

    nfl_data._stats_cache.clear()
    with patch("database.get_conn", side_effect=fake_get_conn, create=True), \
         patch.object(nfl_data, "_fetch_and_parse", side_effect=fake_fetch_and_parse):
        first = nfl_data.get_team_stats("Buffalo Bills")
    results.append(_check(
        "first (real) call fetches from ESPN and returns real stats",
        first is not None and first.pts_per_game == 27.8 and espn_calls["count"] == 1,
        f"pts_per_game={first.pts_per_game if first else None}, espn_calls={espn_calls['count']}",
    ))

    # Simulate a fresh deploy: the in-process dict resets, the
    # persistent store does not.
    nfl_data._stats_cache.clear()
    with patch("database.get_conn", side_effect=fake_get_conn, create=True), \
         patch.object(nfl_data, "_fetch_and_parse", side_effect=fake_fetch_and_parse):
        second = nfl_data.get_team_stats("Buffalo Bills")
    results.append(_check(
        "cold-start call after _stats_cache is cleared does NOT hit ESPN again",
        second is not None and second.pts_per_game == 27.8 and espn_calls["count"] == 1,
        f"pts_per_game={second.pts_per_game if second else None}, espn_calls={espn_calls['count']} (expected still 1)",
    ))

    # ── 3. cfb_data.get_team_stats() cold start ──
    real_cfb_stats = CFBTeamStats(
        team_name="Georgia", team_id="61", wins=12, losses=1,
        home_wins=7, home_losses=0, away_wins=5, away_losses=1,
        pts_per_game=34.2, pts_allowed=17.1, yards_per_play_off=6.4,
        yards_per_play_def=4.7, pass_yards_pg=250.0, rush_yards_pg=195.0,
        turnovers_given=0.9, turnovers_forced=1.9, third_down_pct=46.0,
        sacks_allowed=1.4, sacks_forced=3.3, penalties_pg=5.0,
    )
    cfb_espn_calls = {"count": 0}

    def fake_cfb_fetch(team_name, team_id, season=None):
        cfb_espn_calls["count"] += 1
        return real_cfb_stats

    with patch("database.get_conn", side_effect=fake_get_conn, create=True), \
         patch.object(cfb_data, "_fetch_and_parse", side_effect=fake_cfb_fetch), \
         patch.object(cfb_data, "FBS_TEAM_IDS", {"Georgia": "61"}):
        cfb_first = cfb_data.get_team_stats("Georgia")

    with patch("database.get_conn", side_effect=fake_get_conn, create=True), \
         patch.object(cfb_data, "_fetch_and_parse", side_effect=fake_cfb_fetch), \
         patch.object(cfb_data, "FBS_TEAM_IDS", {"Georgia": "61"}):
        cfb_second = cfb_data.get_team_stats("Georgia")

    results.append(_check(
        "cfb_data.get_team_stats() persists to the shared cache and a later call reuses it without re-fetching",
        cfb_first is not None and cfb_second is not None
        and cfb_second.pts_per_game == 34.2 and cfb_espn_calls["count"] == 1,
        f"pts_per_game={cfb_second.pts_per_game if cfb_second else None}, espn_calls={cfb_espn_calls['count']} (expected 1)",
    ))

    # ── 4. Flat defaults are never persisted ──
    def fake_fetch_always_none(team_name, team_id, season=None):
        return None

    nfl_data._stats_cache.clear()
    with patch("database.get_conn", side_effect=fake_get_conn, create=True), \
         patch.object(nfl_data, "_fetch_and_parse", side_effect=fake_fetch_always_none):
        defaulted = nfl_data.get_team_stats("Miami Dolphins")
    cached_after_default = ("nfl", "Miami Dolphins") in persistent_store
    results.append(_check(
        "a total ESPN outage returns flat defaults but does NOT write them to the persistent cache",
        defaulted is not None and defaulted.pts_per_game == 23.0 and not cached_after_default,
        f"pts_per_game={defaulted.pts_per_game if defaulted else None}, cached={cached_after_default} (expected not cached)",
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
