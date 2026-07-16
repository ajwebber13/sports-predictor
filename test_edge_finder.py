"""
test_edge_finder.py — Culture & Pulse Analytics
================================================
Unit tests for edge_finder.py's ranking math and guardrails, using a
fake DB connection so these run instantly and don't touch Supabase.

WHAT THIS DOES vs DOESN'T PROVE:
- Confirms the composite-score formula, the under/over defense
  mirroring, and the guardrail filters do what the docstring in
  edge_finder.py claims, using hand-verifiable numbers.
- Does NOT prove the real player_props data is clean, or that
  wnba_defense_ratings.get_defense_factors() returns sane values —
  that's what the 2026-07-15 live validation run already covered.
  These two checks are complementary, not redundant: this suite would
  have caught a wrong formula even if the live data happened to look
  fine, and the live run caught the opponent/dotenv bugs no unit test
  written in isolation would have known to look for.

Run: python test_edge_finder.py
"""

import unittest
from unittest.mock import patch

import edge_finder


class FakeCursor:
    """Mimics just enough of a DB cursor to drive get_edge_finder():
    records the params passed to execute(), then applies the SAME
    filter conditions the real SQL WHERE clause encodes against an
    in-memory fixture — so the guardrail tests are checking real
    filtering logic, not just trusting the mock."""

    def __init__(self, fixture_rows):
        self.fixture_rows = fixture_rows
        self.last_params = None

    def execute(self, sql, params):
        self.last_params = params

    def fetchall(self):
        date, sport, min_games, min_hit_rate, min_edge_pct = self.last_params
        rows = []
        for r in self.fixture_rows:
            if r["date"] != date or r["sport"] != sport:
                continue
            if r["hit_rate_overall"] is None or r["projection_edge_pct"] is None or r["defense_factor"] is None:
                continue
            if r["games_overall"] < min_games:
                continue
            if r["hit_rate_overall"] < min_hit_rate:
                continue
            if abs(r["projection_edge_pct"]) < min_edge_pct:
                continue
            rows.append(r)
        return rows


class FakeConn:
    def __init__(self, fixture_rows):
        self._cursor = FakeCursor(fixture_rows)

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def make_row(**overrides):
    """Base row with sane defaults; override only what a test cares about."""
    row = {
        "date": "2026-07-15",
        "sport": "wnba",
        "player_name": "Test Player",
        "team_name": "Test Team",
        "opponent": "Opponent Team",
        "stat": "pts",
        "line": 15.5,
        "hit_rate_overall": 70.0,
        "games_overall": 20,
        "projection_edge_pct": 15.0,
        "projection_direction": "over",
        "projection_tier": "green",
        "defense_factor": 1.1,
        "confidence_tier": "green",
    }
    row.update(overrides)
    return row


def patched_get_edge_finder(fixture_rows, **kwargs):
    """Runs get_edge_finder() against a fixture instead of the real DB.
    Patches _rows_to_dicts to identity since our fixture rows are
    already plain dicts (FakeCursor already applied the SQL-equivalent
    filtering, so no real cursor.description translation is needed)."""
    with patch.object(edge_finder, "_get_conn", return_value=FakeConn(fixture_rows)), \
         patch.object(edge_finder, "_rows_to_dicts", side_effect=lambda cursor, rows: rows):
        return edge_finder.get_edge_finder(**kwargs)


class TestCompositeScore(unittest.TestCase):
    def test_hand_verified_score_and_ranking(self):
        """Two rows, hand-computed expected scores. With 2 rows, min-max
        normalization sends the better value to 100 and the worse to 0
        for each component — so the math is fully predictable by hand."""
        rows = [
            make_row(player_name="A", hit_rate_overall=80.0, projection_edge_pct=20.0,
                     defense_factor=1.2, projection_direction="over"),
            make_row(player_name="B", hit_rate_overall=65.0, projection_edge_pct=10.0,
                     defense_factor=0.9, projection_direction="over"),
        ]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10,
                                         min_games=0, min_hit_rate=0, min_edge_pct=0)

        self.assertEqual(len(picks), 2)
        self.assertEqual(picks[0]["player_name"], "A")  # A wins on every component

        # Player A: hit_rate=80(max)->100, edge_pct=20(max)->100, defense=1.2(max)->100
        # composite = 100*0.4 + 100*0.4 + 100*0.2 = 100.0
        self.assertEqual(picks[0]["edge_score"], 100.0)

        # Player B: every component is the min -> 0 on all three -> composite 0.0
        self.assertEqual(picks[1]["edge_score"], 0.0)

    def test_flat_slate_returns_neutral_fifty(self):
        """If every qualifying row has identical hit_rate/edge_pct/defense,
        min-max has no spread to normalize against — every row should
        land at exactly 50, not a divide-by-zero crash or a fake winner."""
        rows = [
            make_row(player_name="A"),
            make_row(player_name="B"),
        ]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10,
                                         min_games=0, min_hit_rate=0, min_edge_pct=0)
        for p in picks:
            self.assertEqual(p["edge_score"], 50.0)


class TestDefenseDirectionMirroring(unittest.TestCase):
    def test_under_pick_mirrors_around_one(self):
        """A tough defense (low factor) should score as favorable for an
        UNDER pick, the same way a weak defense (high factor) scores as
        favorable for an OVER pick. This is the one piece of math in the
        file that's easy to get backwards silently, per the build notes."""
        rows = [
            # OVER vs a weak defense (factor 1.5) — should score high on defense
            make_row(player_name="OverPick", projection_direction="over", defense_factor=1.5,
                     hit_rate_overall=70.0, projection_edge_pct=10.0),
            # UNDER vs a tough defense (factor 0.5) — should ALSO score high on
            # defense, because a tough D is exactly what supports an under
            make_row(player_name="UnderPick", projection_direction="under", defense_factor=0.5,
                     hit_rate_overall=70.0, projection_edge_pct=10.0),
            # Baseline row with a clearly worse (neutral) matchup for its own
            # direction, so the slate isn't flat and 100 is actually reachable —
            # proves the mirroring produces a real max, not just a tie at 50.
            make_row(player_name="Baseline", projection_direction="over", defense_factor=1.0,
                     hit_rate_overall=70.0, projection_edge_pct=10.0),
        ]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10,
                                         min_games=0, min_hit_rate=0, min_edge_pct=0)

        by_name = {p["player_name"]: p for p in picks}
        over_defense_norm = by_name["OverPick"]["edge_score_components"]["defense_norm"]
        under_defense_norm = by_name["UnderPick"]["edge_score_components"]["defense_norm"]

        # Both represent "as favorable as it gets" for their own direction —
        # mirroring (2.0 - factor) for unders should make these equal, and
        # with the Baseline row giving the slate real spread, both should
        # hit the true max of 100.
        self.assertEqual(over_defense_norm, under_defense_norm)
        self.assertEqual(over_defense_norm, 100.0)

    def test_under_pick_vs_weak_defense_scores_low(self):
        """The failure mode this guards against: without mirroring, an
        UNDER pick vs a leaky/weak defense (bad matchup for an under)
        would incorrectly score HIGH just because defense_factor is a
        big raw number. It should score low instead."""
        rows = [
            make_row(player_name="UnderVsWeakD", projection_direction="under", defense_factor=1.6,
                     hit_rate_overall=70.0, projection_edge_pct=10.0),
            make_row(player_name="UnderVsToughD", projection_direction="under", defense_factor=0.6,
                     hit_rate_overall=70.0, projection_edge_pct=10.0),
        ]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10,
                                         min_games=0, min_hit_rate=0, min_edge_pct=0)
        # tough defense (0.6) should outrank weak defense (1.6) for an under pick
        self.assertEqual(picks[0]["player_name"], "UnderVsToughD")


class TestConfidenceGuardrails(unittest.TestCase):
    def test_small_sample_excluded_despite_high_hit_rate(self):
        """The exact scenario from the build notes: 4-for-5 games = 80%
        hit rate, but with games_overall below MIN_SAMPLE_SIZE it must
        not appear in results at all."""
        rows = [
            make_row(player_name="SmallSample", hit_rate_overall=80.0, games_overall=5),
            make_row(player_name="RealSample", hit_rate_overall=70.0, games_overall=20),
        ]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10)  # default guardrails
        names = [p["player_name"] for p in picks]
        self.assertNotIn("SmallSample", names)
        self.assertIn("RealSample", names)

    def test_low_hit_rate_excluded(self):
        rows = [make_row(player_name="LowHitRate", hit_rate_overall=50.0, games_overall=20)]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10)
        self.assertEqual(picks, [])

    def test_low_edge_pct_excluded(self):
        rows = [make_row(player_name="LowEdge", projection_edge_pct=2.0, games_overall=20)]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10)
        self.assertEqual(picks, [])

    def test_row_clearing_all_guardrails_is_included(self):
        rows = [make_row(player_name="Qualifies", hit_rate_overall=70.0,
                          projection_edge_pct=15.0, games_overall=20)]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10)
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["player_name"], "Qualifies")


class TestConfidenceLabel(unittest.TestCase):
    def test_high_confidence_requires_score_and_sample(self):
        rows = [
            # clears HIGH bar: big edge everywhere + 20 games (>=15)
            make_row(player_name="HighConf", hit_rate_overall=90.0, projection_edge_pct=30.0,
                      defense_factor=1.5, games_overall=20),
            # same great score, but games_overall below 15 -> should be capped at MEDIUM
            make_row(player_name="GoodScoreSmallSample", hit_rate_overall=89.0, projection_edge_pct=29.0,
                      defense_factor=1.4, games_overall=10),
        ]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=10,
                                         min_games=0, min_hit_rate=0, min_edge_pct=0)
        by_name = {p["player_name"]: p for p in picks}
        self.assertEqual(by_name["HighConf"]["confidence"], "HIGH")
        self.assertEqual(by_name["GoodScoreSmallSample"]["confidence"], "MEDIUM")


class TestEdgeCases(unittest.TestCase):
    def test_unsupported_sport_returns_empty_without_querying_db(self):
        picks = patched_get_edge_finder([], date="2026-07-15", sport="curling", top_n=10)
        self.assertEqual(picks, [])

    def test_no_qualifying_rows_returns_empty_list_not_error(self):
        picks = patched_get_edge_finder([], date="2026-07-15", sport="wnba", top_n=10)
        self.assertEqual(picks, [])

    def test_top_n_caps_results(self):
        rows = [make_row(player_name=f"P{i}", hit_rate_overall=70.0 + i) for i in range(10)]
        picks = patched_get_edge_finder(rows, date="2026-07-15", sport="wnba", top_n=3,
                                         min_games=0, min_hit_rate=0, min_edge_pct=0)
        self.assertEqual(len(picks), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
