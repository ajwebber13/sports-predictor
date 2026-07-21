#!/usr/bin/env python3
"""
threshold_sweep.py

Sweeps strong/fade thresholds against MLB picks-only props to find the
win-rate-optimal cutoff.

SCHEMA NOTES (confirmed via inspect_schema.py):
  - player_props and prop_results have NO shared foreign key. They are
    joined here on a natural key: date + sport + player_name + stat + line.
  - sport values are lowercase ('mlb', 'wnba'), not 'MLB'.
  - prop_results.hit is an integer 0/1, not a text result column.
  - There is no `effective_confidence` column anywhere. The 66.4% number
    from earlier calibration work was NOT reading a stored field -- it was
    computed some other way (possibly inline in a different script). This
    script can't reproduce it directly; see compare section below for what
    it does instead.

Set DATABASE_URL env var before running.
"""

import os
import sys
from itertools import product

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("Set DATABASE_URL env var (Supabase connection string) before running.")

STRONG_THRESHOLDS = [65, 70, 75, 80]
FADE_THRESHOLDS = [20, 25, 30, 35]

SPORT = "mlb"  # lowercase, confirmed via schema inspection


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def fetch_base_population(conn):
    """
    Every graded prop for the sport, joined on the natural key, with its
    hit_rate_overall and win/loss (hit) result. No tier/threshold filter
    applied here -- the sweep recomputes membership itself.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                pp.id,
                pp.hit_rate_overall,
                pp.confidence_tier,
                pr.hit
            FROM player_props pp
            JOIN prop_results pr
              ON pr.date = pp.date
             AND pr.sport = pp.sport
             AND pr.player_name = pp.player_name
             AND pr.stat = pp.stat
             AND pr.line = pp.line
            WHERE pp.sport = %s
              AND pr.hit IS NOT NULL
            """,
            (SPORT,),
        )
        return cur.fetchall()


def win_rate(rows):
    n = len(rows)
    if n == 0:
        return None, 0
    wins = sum(1 for r in rows if r["hit"] == 1)
    return wins / n, n


def sweep(rows):
    print(f"\n{'strong':>7} {'fade':>7} {'n':>6} {'win_rate':>10}")
    print("-" * 34)
    results = []
    for strong, fade in product(STRONG_THRESHOLDS, FADE_THRESHOLDS):
        picks = [
            r
            for r in rows
            if r["hit_rate_overall"] is not None
            and (r["hit_rate_overall"] >= strong or r["hit_rate_overall"] <= fade)
        ]
        wr, n = win_rate(picks)
        if wr is not None:
            print(f"{strong:>7} {fade:>7} {n:>6} {wr*100:>9.1f}%")
            results.append((strong, fade, n, wr))
    return results


def check_join_yield(conn):
    """
    Sanity check: how many player_props rows for this sport find a matching
    prop_results row at all via the natural-key join? A low match rate would
    mean the natural key isn't reliable (e.g. duplicate player/stat/line
    combos on the same date, or formatting mismatches between the two
    tables) and the whole sweep is running on a biased subset.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM player_props WHERE sport = %s", (SPORT,))
        total_props = cur.fetchone()["n"]

        cur.execute(
            """
            SELECT COUNT(*) AS n
            FROM player_props pp
            JOIN prop_results pr
              ON pr.date = pp.date AND pr.sport = pp.sport
             AND pr.player_name = pp.player_name AND pr.stat = pp.stat
             AND pr.line = pp.line
            WHERE pp.sport = %s
            """,
            (SPORT,),
        )
        matched = cur.fetchone()["n"]

    print(f"\nJoin yield check ({SPORT}):")
    print(f"  player_props rows: {total_props}")
    print(f"  matched to a prop_results row: {matched}")
    if total_props:
        print(f"  match rate: {matched/total_props*100:.1f}%")
    if total_props and matched / total_props < 0.5:
        print(
            "  [!] Less than half of props have a graded result via this join. "
            "Either most props are ungraded/pending, or the natural key is "
            "unreliable (check for duplicate player+stat+line+date rows, or "
            "formatting differences like trailing whitespace in player_name)."
        )


def main():
    conn = get_conn()
    try:
        check_join_yield(conn)
        rows = fetch_base_population(conn)
        print(f"\nBase population ({SPORT}, graded via natural-key join): {len(rows)} rows")
        sweep(rows)
        print(
            "\nNote: 'effective_confidence' does not exist as a column -- the "
            "66.4% figure from earlier calibration can't be reproduced here "
            "directly. If you still have that script/query, share it and I'll "
            "fold it into this comparison properly instead of guessing."
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
