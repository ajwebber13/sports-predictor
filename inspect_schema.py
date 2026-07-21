#!/usr/bin/env python3
"""
inspect_schema.py

Dumps column names/types for player_props and prop_results (plus a sample
row from each) so we can fix the column-name guesses in threshold_sweep.py
and tier_discrepancy_check.py to match your actual schema.

    python inspect_schema.py
"""

import os
import sys

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    sys.exit("Set DATABASE_URL env var before running.")

TABLES = ["player_props", "prop_results"]


def main():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        with conn.cursor() as cur:
            # List all tables first, in case names differ from our guess
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )
            print("Tables in public schema:")
            for row in cur.fetchall():
                print(f"  {row['table_name']}")

        for table in TABLES:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (table,),
                )
                cols = cur.fetchall()
            print(f"\n{table} columns:")
            if not cols:
                print("  [table not found]")
                continue
            for c in cols:
                print(f"  {c['column_name']:<25} {c['data_type']}")

            with conn.cursor() as cur:
                try:
                    cur.execute(f"SELECT * FROM {table} LIMIT 1")
                    sample = cur.fetchone()
                    print(f"\n{table} sample row:")
                    if sample:
                        for k, v in sample.items():
                            print(f"  {k}: {v}")
                    else:
                        print("  [empty table]")
                except psycopg2.Error as e:
                    conn.rollback()
                    print(f"  [couldn't fetch sample: {e}]")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
