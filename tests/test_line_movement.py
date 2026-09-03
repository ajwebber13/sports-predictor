"""
tests/test_line_movement.py — Culture & Pulse Analytics
================================================================
Regression tests for database.py's line-movement fixes (2026-09-04),
after a real false alert: "Colts @ Chiefs home line moved -15 pts".

Root cause: log_odds()/update_closing_odds()/log_line_movement() each
scanned every bookmaker's h2h outcomes and kept whichever one was LAST
in the list -- not a specific, consistent bookmaker. get_live_odds()
only ever returns draftkings/fanduel, but their order in the API
response isn't guaranteed call to call, so "opening" (captured this
morning) and "current" (captured on a later retry) could silently come
from two different books -- a real DraftKings-vs-FanDuel price gap read
as a 15-point market move that never happened.

Also covers the new sport-specific data-error ceiling
(LINE_MOVEMENT_DATA_ERROR_PTS): a single move bigger than that isn't
real sharp action, and is logged instead of surfacing a false alert.

Usage:
    py tests/test_line_movement.py
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


def _game_with_books(home_team, away_team, books: dict) -> dict:
    """books: {book_key: (home_price, away_price)}"""
    return {
        "home_team": home_team, "away_team": away_team,
        "bookmakers": [
            {"key": key, "markets": [{"key": "h2h", "outcomes": [
                {"name": home_team, "price": prices[0]},
                {"name": away_team, "price": prices[1]},
            ]}]}
            for key, prices in books.items()
        ],
    }


class _FakeCursor:
    """Minimal cursor stand-in: returns a fixed opening row for the
    SELECT in log_line_movement, records INSERT/UPDATE calls."""
    def __init__(self, opening_row):
        self.opening_row = opening_row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql.strip(), params))
        return self

    def fetchone(self):
        return self.opening_row


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
    def cursor(self):
        return self._cursor
    def commit(self):
        pass
    def rollback(self):
        pass
    def close(self):
        pass


def run():
    results = []

    print("Testing _get_h2h_prices() picks one consistent bookmaker...")
    game = _game_with_books("Kansas City Chiefs", "Indianapolis Colts", {
        "fanduel": (-125, 105),      # listed FIRST here on purpose
        "draftkings": (-110, -110),  # preferred book should win regardless of order
    })
    home_ml, away_ml = database._get_h2h_prices(game, "Kansas City Chiefs", "Indianapolis Colts")
    results.append(_check(
        "draftkings (first in PREFERRED_BOOKMAKERS) wins even when listed second in the response",
        (home_ml, away_ml) == (-110, -110),
        f"got ({home_ml}, {away_ml}), expected (-110, -110)",
    ))

    game_dk_missing = _game_with_books("Kansas City Chiefs", "Indianapolis Colts", {
        "fanduel": (-125, 105),
    })
    home_ml2, away_ml2 = database._get_h2h_prices(game_dk_missing, "Kansas City Chiefs", "Indianapolis Colts")
    results.append(_check(
        "falls back to fanduel when draftkings isn't present",
        (home_ml2, away_ml2) == (-125, 105),
        f"got ({home_ml2}, {away_ml2})",
    ))

    game_neither = _game_with_books("Kansas City Chiefs", "Indianapolis Colts", {
        "betmgm": (-125, 105),
    })
    home_ml3, away_ml3 = database._get_h2h_prices(game_neither, "Kansas City Chiefs", "Indianapolis Colts")
    results.append(_check(
        "returns (None, None) when neither preferred book is present, rather than a wrong price",
        (home_ml3, away_ml3) == (None, None),
        f"got ({home_ml3}, {away_ml3})",
    ))

    print("\nTesting log_line_movement() reproduces and fixes the real Colts @ Chiefs case...")
    # The real incident, reconstructed: DraftKings had Chiefs -110 this
    # morning (the stored "opening"); this run's live feed lists FanDuel
    # FIRST with Chiefs -125, but DraftKings (still -110, no real move)
    # is also present. The old "last bookmaker iterated" logic would
    # have picked FanDuel's -125 -> a fake "-15" movement. The fix must
    # resolve to DraftKings -110 both times -> zero real movement.
    game_live = _game_with_books("Kansas City Chiefs", "Indianapolis Colts", {
        "fanduel": (-125, 105),
        "draftkings": (-110, -110),
    })
    opening_row = {"opening_home_ml": -110, "opening_away_ml": -110}
    fake_cursor = _FakeCursor(opening_row)
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor)):
        sharp_hits = database.log_line_movement("nfl", [game_live])
    results.append(_check(
        "no false sharp alert once opening and current both resolve to the same book (DraftKings)",
        sharp_hits == [],
        f"sharp_hits={sharp_hits}",
    ))

    print("\nTesting the sport-specific data-error ceiling (>7 NFL, >10 CFB logs, doesn't alert)...")
    # A genuinely large single-book move (not a cross-book artifact) --
    # 15pt swing on the SAME book. Real sharp action never gets this big
    # in one session; this is what the ceiling is for.
    game_bad = _game_with_books("Kansas City Chiefs", "Indianapolis Colts", {
        "draftkings": (-125, 105),
    })
    opening_row2 = {"opening_home_ml": -110, "opening_away_ml": -110}
    fake_cursor2 = _FakeCursor(opening_row2)
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor2)):
        sharp_hits2 = database.log_line_movement("nfl", [game_bad])
    results.append(_check(
        "a >7pt NFL move (implausible) is logged as a data error, not alerted",
        sharp_hits2 == [],
        f"sharp_hits={sharp_hits2}",
    ))

    # A move within the plausible range (<=10 total but still >=10 to
    # trigger the pre-existing sharp threshold) for a sport with NO
    # data-error ceiling configured (e.g. wnba) should still alert as
    # before -- the ceiling is sport-specific and opt-in, not a global
    # behavior change.
    game_wnba = _game_with_books("Team A", "Team B", {"draftkings": (-125, 105)})
    opening_row3 = {"opening_home_ml": -110, "opening_away_ml": -110}
    fake_cursor3 = _FakeCursor(opening_row3)
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor3)):
        sharp_hits3 = database.log_line_movement("wnba", [game_wnba])
    results.append(_check(
        "a sport with no configured data-error ceiling (wnba) keeps the old sharp-alert behavior",
        len(sharp_hits3) == 1,
        f"sharp_hits={sharp_hits3}",
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
