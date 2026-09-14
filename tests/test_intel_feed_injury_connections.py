"""
tests/test_intel_feed_injury_connections.py — Culture & Pulse Analytics
========================================================================
Regression test for the actual /nfl/edges 280s-hang root cause found
2026-09-14: InjuryReport._calc_impact() opened its OWN database
connection per injured player (dozens per league-wide fetch_injuries()
call) instead of sharing one. Confirmed live: fetch_injuries('NFL')
measured 420-450s before this fix, ~52s after (800 injury reports,
32 teams) — the ESPN call itself was never the slow part (consistently
under 1s), which is why the earlier _run_with_deadline() wrapper around
it alone didn't fix the reported symptom.

This test doesn't hit the network or a real database — it mocks
database.get_conn() and counts how many times it's actually called
across a batch of InjuryReports, which is the thing that regressed.

Usage:
    py tests/test_intel_feed_injury_connections.py
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import intel_feed


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


class _FakeCursor:
    def execute(self, sql, params=None):
        pass
    def fetchone(self):
        return None  # no profile match -> falls back to base_impact * NO_PROFILE_DISCOUNT


class _FakeConn:
    def __init__(self):
        self.cursor_calls = 0
    def cursor(self):
        self.cursor_calls += 1
        return _FakeCursor()
    def close(self):
        pass


def run():
    results = []

    print("Testing InjuryReport with an explicit db_cursor never opens its own connection...")
    with patch("database.get_conn") as mock_get_conn:
        shared_cursor = _FakeCursor()
        report = intel_feed.InjuryReport(
            "Kansas City Chiefs", "Test Player", "QB", "Out", "test",
            league="nfl", db_cursor=shared_cursor,
        )
        results.append(_check(
            "get_conn() is never called when db_cursor is provided",
            mock_get_conn.call_count == 0,
            f"get_conn call_count={mock_get_conn.call_count}",
        ))
        results.append(_check(
            "impact is still computed (falls back to base_impact, no profile match)",
            isinstance(report.impact, float) and report.impact > 0,
            f"impact={report.impact}",
        ))

    print("\nTesting the OLD per-report behavior still works when db_cursor is omitted...")
    fake_conn = _FakeConn()
    with patch("database.get_conn", return_value=fake_conn) as mock_get_conn:
        intel_feed.InjuryReport("Kansas City Chiefs", "Test Player", "QB", "Out", "test", league="nfl")
        results.append(_check(
            "backward-compat path (no db_cursor) still opens its own connection",
            mock_get_conn.call_count == 1,
            f"get_conn call_count={mock_get_conn.call_count}",
        ))

    print("\nTesting fetch_injuries() opens exactly ONE connection for a multi-player batch...")
    fake_data = {
        "injuries": [
            {"displayName": "Kansas City Chiefs", "injuries": [
                {"athlete": {"displayName": "Player A", "position": {"abbreviation": "QB"}}, "status": "Out"},
                {"athlete": {"displayName": "Player B", "position": {"abbreviation": "RB"}}, "status": "Questionable"},
            ]},
            {"displayName": "Buffalo Bills", "injuries": [
                {"athlete": {"displayName": "Player C", "position": {"abbreviation": "WR"}}, "status": "Doubtful"},
            ]},
        ]
    }
    fake_conn2 = _FakeConn()
    with patch.object(intel_feed, "_run_with_deadline", return_value=fake_data), \
         patch("database.get_conn", return_value=fake_conn2) as mock_get_conn2:
        result = intel_feed.fetch_injuries("NFL")

    total_reports = sum(len(v) for v in result.values())
    results.append(_check(
        "fetch_injuries() opens exactly 1 connection regardless of player count (was 1-per-player)",
        mock_get_conn2.call_count == 1,
        f"get_conn call_count={mock_get_conn2.call_count} (3 players processed)",
    ))
    results.append(_check(
        "all 3 injury reports across both teams were still built correctly",
        total_reports == 3 and "Kansas City Chiefs" in result and "Buffalo Bills" in result,
        f"result={ {k: len(v) for k, v in result.items()} }",
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
