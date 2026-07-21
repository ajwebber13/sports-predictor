#!/usr/bin/env python3
"""
tier_discrepancy_check.py

Checks whether confidence_tier (a label) actually corresponds to the
hit_rate_overall ranges it should, given the fixed 80/20 rule. Also
recomputes the ELITE/HIGH/GOOD win-rate anomaly (item 5) directly from
hit_rate_overall, bypassing the stored tier label.

SCHEMA NOTES (confirmed via inspect_schema.py):
  - sport values are lowercase ('mlb', 'wnba').
  - player_props has no updated_at column -- only captured_at. Since
    confidence_tier and hit_rate_overall are written together in the same
    row at capture time with no later update column, the "tier goes stale
    after capture" hypothesis doesn't hold for this schema. Dropped that
    check. If hit_rate_overall or confidence_tier CAN be recomputed later
    by some other process (outside this table), that would need to be
    checked in that process's code, not here.
  - player_props/prop_results join on a natural key (date, sport,
    player_name, stat, line) -- there is no shared id/FK.
  - prop_results.hit is 0/1 integer, not a text result column.

Set DATABASE_URL env var before running.
"""

import os
import sys

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("Set DATABASE_URL env var (Supabase connection string) before running.")

SPORT = "mlb"


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def check_tier_vs_hit_rate_ranges(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                confidence_tier,
                COUNT(*) AS n,
                MIN(hit_rate_overall) AS min_hr,
                MAX(hit_rate_overall) AS max_hr,
                AVG(hit_rate_overall) AS avg_hr
            FROM player_props
            WHERE sport = %s
            GROUP BY confidence_tier
            ORDER BY confidence_tier
            """,
            (SPORT,),
        )
        rows = cur.fetchall()
    print(f"\nconfidence_tier vs hit_rate_overall range check ({SPORT}):")
    print(f"{'tier':<12} {'n':>6} {'min_hr':>8} {'max_hr':>8} {'avg_hr':>8}")
    print("-" * 46)
    for r in rows:
        min_hr = r["min_hr"] if r["min_hr"] is not None else float("nan")
        max_hr = r["max_hr"] if r["max_hr"] is not None else float("nan")
        avg_hr = r["avg_hr"] if r["avg_hr"] is not None else float("nan")
        print(f"{str(r['confidence_tier']):<12} {r['n']:>6} {min_hr:>8.1f} {max_hr:>8.1f} {avg_hr:>8.1f}")
    print(
        "\nRed flag: a 'green' row with min_hr well under 80, or a non-green "
        "tier with max_hr well over 80 -- label and number disagree at "
        "capture time (not staleness -- this schema writes both together)."
    )


def check_tier_ordering_anomaly(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                CASE
                    WHEN pp.hit_rate_overall >= 75 THEN 'ELITE (75+)'
                    WHEN pp.hit_rate_overall >= 70 THEN 'HIGH (70-75)'
                    WHEN pp.hit_rate_overall >= 65 THEN 'GOOD (65-70)'
                    ELSE 'OTHER'
                END AS bucket,
                COUNT(*) AS n,
                SUM(pr.hit)::float / COUNT(*) AS win_rate
            FROM player_props pp
            JOIN prop_results pr
              ON pr.date = pp.date AND pr.sport = pp.sport
             AND pr.player_name = pp.player_name AND pr.stat = pp.stat
             AND pr.line = pp.line
            WHERE pp.sport = %s AND pr.hit IS NOT NULL
            GROUP BY bucket
            ORDER BY bucket
            """,
            (SPORT,),
        )
        rows = cur.fetchall()
    print("\nWin rate by hit_rate_overall bucket (recomputed, not using stored tier):")
    for r in rows:
        print(f"  {r['bucket']:<14} n={r['n']:<6} win_rate={r['win_rate']*100:.1f}%")
    print(
        "If ELITE still underperforms HIGH/GOOD here, the anomaly is real "
        "and worth investigating on its own -- not a tier-labeling artifact."
    )


def check_duplicate_natural_keys(conn):
    """
    The natural-key join (date+sport+player_name+stat+line) assumes each
    combo is unique per table. If not, the join fans out and inflates
    counts. Worth checking directly.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT date, player_name, stat, line, COUNT(*) AS n
            FROM player_props
            WHERE sport = %s
            GROUP BY date, player_name, stat, line
            HAVING COUNT(*) > 1
            LIMIT 10
            """,
            (SPORT,),
        )
        dupes = cur.fetchall()
    print(f"\nDuplicate (date, player_name, stat, line) combos in player_props ({SPORT}):")
    if not dupes:
        print("  none found in first check -- natural key looks unique")
    else:
        print(f"  {len(dupes)}+ duplicate combos found, e.g.:")
        for d in dupes:
            print(f"    {d}")
        print(
            "  [!] The natural-key join will fan out on these rows, inflating "
            "match counts. Consider adding a real prop_id FK, or dedupe before "
            "joining."
        )


def main():
    conn = get_conn()
    try:
        check_tier_vs_hit_rate_ranges(conn)
        check_tier_ordering_anomaly(conn)
        check_duplicate_natural_keys(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
