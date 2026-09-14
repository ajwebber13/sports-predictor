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

Also covers the sport-specific data-error ceiling
(LINE_MOVEMENT_DATA_ERROR_PTS): a single move bigger than that isn't
real sharp action, and is logged instead of surfacing a false alert.

Extended 2026-09-14 for the WNBA line-movement bug (a 12-pt "sharp"
alert on a -310 favorite that was really a 0.7pp implied-probability
move): added SHARP_MOVE_MIN_PROB_DELTA_PTS (global, implied-probability
based, additive to the existing raw-points threshold) and a WNBA entry
in LINE_MOVEMENT_DATA_ERROR_PTS (catches genuine feed corruption like
-115 -> -100000, distinct from the steep-line false positives the
probability filter handles).

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

    # A real near-even-money move (-110 -> -125, 15 raw pts, 3.2pp
    # implied-probability shift) should still alert for a sport with no
    # data-error ceiling configured beyond WNBA (e.g. a hypothetical
    # future sport) -- neither new WNBA-specific protection added
    # 2026-09-14 is a blanket "no sport but nfl/cfb ever alerts" change.
    game_other_sport = _game_with_books("Team A", "Team B", {"draftkings": (-125, 105)})
    opening_row3 = {"opening_home_ml": -110, "opening_away_ml": -110}
    fake_cursor3 = _FakeCursor(opening_row3)
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor3)):
        sharp_hits3 = database.log_line_movement("ncaab", [game_other_sport])
    results.append(_check(
        "a real near-even-money move still alerts for a sport with no configured protections",
        len(sharp_hits3) == 1,
        f"sharp_hits={sharp_hits3}",
    ))

    print("\nTesting the 2026-09-14 WNBA fix: proportionally-trivial moves on steep lines...")
    # The actual reported bug, reconstructed: Sparks @ Wings, DraftKings
    # -310 -> -298 (12 raw pts, clears the flat >=10 bar) but only a
    # 0.7pp real implied-probability shift -- not sharp action. Must be
    # silently suppressed (no alert, no data-error log either -- it's
    # a real quote, just not a meaningful move).
    game_steep = _game_with_books("Dallas Wings", "Los Angeles Sparks", {"draftkings": (-298, 240)})
    opening_row4 = {"opening_home_ml": -310, "opening_away_ml": 250}
    fake_cursor4 = _FakeCursor(opening_row4)
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor4)):
        sharp_hits4 = database.log_line_movement("wnba", [game_steep])
    results.append(_check(
        "Sparks @ Wings -310 -> -298 (12 raw pts, 0.7pp real) does NOT fire as sharp",
        sharp_hits4 == [],
        f"sharp_hits={sharp_hits4}",
    ))

    # The actual feed-corruption incident, reconstructed: Sparks @ Storm,
    # -115 -> -100000 in one session -- not a real bookmaker price.
    # Must be caught by WNBA's new 5000pt data-error ceiling, not
    # surfaced as a (technically real per the flat threshold) alert.
    game_corrupt = _game_with_books("Seattle Storm", "Los Angeles Sparks", {"draftkings": (-100000, 115)})
    opening_row5 = {"opening_home_ml": -115, "opening_away_ml": 105}
    fake_cursor5 = _FakeCursor(opening_row5)
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor5)):
        sharp_hits5 = database.log_line_movement("wnba", [game_corrupt])
    results.append(_check(
        "-115 -> -100000 (feed corruption, not a real price) is caught as a WNBA data error, not alerted",
        sharp_hits5 == [],
        f"sharp_hits={sharp_hits5}",
    ))

    # A genuinely real WNBA move on a lopsided line -- -480 -> -2500 is
    # a big raw number (2,020 pts) but also a real 13.4pp implied-
    # probability shift (e.g. a late star-player scratch). Must still
    # fire, proving the new filters suppress noise without silencing
    # real signal.
    game_real_steep = _game_with_books("Seattle Storm", "Minnesota Lynx", {"draftkings": (-2500, 400)})
    opening_row6 = {"opening_home_ml": -480, "opening_away_ml": 400}
    fake_cursor6 = _FakeCursor(opening_row6)
    with patch.object(database, "get_conn", return_value=_FakeConn(fake_cursor6)):
        sharp_hits6 = database.log_line_movement("wnba", [game_real_steep])
    results.append(_check(
        "-480 -> -2500 (real 13.4pp shift, not corrupted) still fires as sharp",
        len(sharp_hits6) == 1,
        f"sharp_hits={sharp_hits6}",
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
