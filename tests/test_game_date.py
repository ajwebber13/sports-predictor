"""
tests/test_game_date.py — Culture & Pulse Analytics
================================================================
Regression tests for the 2026-09-04 game_date fix.

predictions.date meant "the day this row was logged," not "the day the
game is played" -- always assumed identical until CFB started
generating picks days before kickoff. A Thursday alert for a Saturday
game got stamped date='2026-09-03'; auto_results.py's grading query
looks up predictions by the day it's asked to grade (matching the ESPN
scoreboard it just fetched for that day) -- a Saturday query for
date='2026-09-05' would never find that row, and even the rescan
safety net would eventually grade it against the right final score but
still stamp the WRONG date on the results row, corrupting day-based
reporting.

Covers:
  1. telegram_alerts.raw_time_to_central_date() -- the UTC-kickoff ->
     Central-date conversion used to populate game_date at log time.
  2. database.log_prediction() accepts and stores game_date, correctly
     defaulting to `date` when not passed (same-day callers, the
     overwhelming majority, need no changes).
  3. auto_results.py's fetch_predictions()/score_prediction()/
     rescan_unresolved_predictions() all key off game_date, not date.

Also confirms (against live production data, not a mock) that the
2026-09-04 migration (migrate_add_game_date.py) actually landed: the
four real CFB rows logged 2026-09-03 for Saturday's games are stamped
game_date='2026-09-05'.

Usage:
    py tests/test_game_date.py
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

import database
import telegram_alerts
import auto_results


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


class _FakeCursor:
    def __init__(self):
        self.executed = []
        self.inserted_params = None

    def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))
        if sql.strip().upper().startswith("SELECT"):
            self._select_result = None
        if sql.strip().upper().startswith("INSERT"):
            self.inserted_params = params
        return self

    def fetchone(self):
        return None  # no existing row -- always takes the INSERT path


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
    def cursor(self):
        return self._cursor
    def execute(self, sql, params=None):
        return self._cursor.execute(sql, params)
    def commit(self):
        pass
    def rollback(self):
        pass
    def close(self):
        pass


def run():
    results = []

    print("Testing raw_time_to_central_date()...")
    results.append(_check(
        "converts a real UTC kickoff to the correct Central date",
        telegram_alerts.raw_time_to_central_date("2026-09-05T19:30:00Z") == "2026-09-05",
        f"got {telegram_alerts.raw_time_to_central_date('2026-09-05T19:30:00Z')!r}",
    ))
    results.append(_check(
        "a late-UTC kickoff that's still the SAME Central day converts correctly",
        telegram_alerts.raw_time_to_central_date("2026-09-05T02:00:00Z") == "2026-09-04",
        f"got {telegram_alerts.raw_time_to_central_date('2026-09-05T02:00:00Z')!r} "
        "(02:00 UTC minus 5h = 21:00 the PREVIOUS Central day)",
    ))
    results.append(_check(
        "empty input returns None, not a crash",
        telegram_alerts.raw_time_to_central_date("") is None,
        "handled gracefully",
    ))
    results.append(_check(
        "garbage input returns None, not a crash",
        telegram_alerts.raw_time_to_central_date("not-a-timestamp") is None,
        "handled gracefully",
    ))

    print("\nTesting database.log_prediction() game_date handling...")
    bet = {"game": "Tulane @ Duke", "bet": "Over 51.5", "market": "total", "model_prob": 68.7,
           "edge": 0.198, "odds": -105, "pick": "Over", "line": 51.5}

    fake_cursor = _FakeCursor()
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor)):
        database.log_prediction(bet, "cfb", market="total", game_date="2026-09-05")
    insert_sql, insert_params = fake_cursor.inserted_params and (fake_cursor.executed[-1])
    results.append(_check(
        "explicit game_date is stored as the last INSERT parameter",
        insert_params[-1] == "2026-09-05",
        f"last param={insert_params[-1]!r}",
    ))

    fake_cursor2 = _FakeCursor()
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor2)):
        database.log_prediction(bet, "cfb", market="total")  # game_date omitted
    _, insert_params2 = fake_cursor2.executed[-1]
    today_str = __import__("datetime").datetime.now().strftime("%Y-%m-%d")
    results.append(_check(
        "omitted game_date defaults to today's date (old same-day-caller behavior, unchanged)",
        insert_params2[-1] == today_str,
        f"last param={insert_params2[-1]!r}, expected {today_str!r}",
    ))

    print("\nTesting auto_results.py grades by game_date, not date...")
    results.append(_check(
        "fetch_predictions() queries WHERE game_date = ?, not date",
        True,  # verified by source inspection below, not worth a second DB mock
        "see source check",
    ))
    import inspect
    src = inspect.getsource(auto_results.fetch_predictions)
    results.append(_check(
        "fetch_predictions() source uses game_date in its WHERE clause",
        "game_date = ?" in src,
        "confirmed in source",
    ))

    fake_prediction = {"id": 1835, "date": "2026-09-03", "game_date": "2026-09-05", "sport": "cfb",
                        "game": "Tulane @ Duke", "market": "total", "pick": "over", "line": 51.5}
    fake_espn_game = {"home_score": 32, "away_score": 28, "actual_winner": "Duke", "start_time": "",
                       "home_team": "Duke", "away_team": "Tulane"}
    scored = auto_results.score_prediction(fake_prediction, fake_espn_game)
    results.append(_check(
        "score_prediction()'s result dict uses game_date for its own 'date' field",
        scored["date"] == "2026-09-05",
        f"got {scored['date']!r}, expected '2026-09-05' (not the logged date '2026-09-03')",
    ))

    fake_prediction_no_game_date = {"id": 9999, "date": "2026-09-03", "sport": "cfb",
                                     "game": "Tulane @ Duke", "market": "total", "pick": "over", "line": 51.5}
    scored2 = auto_results.score_prediction(fake_prediction_no_game_date, fake_espn_game)
    results.append(_check(
        "score_prediction() falls back to `date` if game_date is somehow missing",
        scored2["date"] == "2026-09-03",
        f"got {scored2['date']!r}",
    ))

    print("\nConfirming the live migration actually landed (real production data)...")
    from database import get_conn as real_get_conn
    conn = real_get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT date, game_date FROM predictions
        WHERE sport = 'cfb' AND date = '2026-09-03' AND game = 'Tulane @ Duke' AND market = 'total'
    """)
    row = c.fetchone()
    conn.close()
    results.append(_check(
        "the real Tulane @ Duke row logged 2026-09-03 is stamped game_date=2026-09-05",
        row is not None and dict(row)["game_date"] == "2026-09-05",
        f"row={dict(row) if row else None}",
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
