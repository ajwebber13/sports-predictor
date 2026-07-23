"""
backfill_results.py — Culture & Pulse Analytics
================================================
One-time script: scores every date between two dates using the
same logic as auto_results.py. Use this to fill the gap left by
the broken pipeline (6/28 - 7/3).

Usage:
    python backfill_results.py 2026-06-28 2026-07-03
"""

import sys
from datetime import datetime, timedelta
from auto_results import run


def daterange(start_str: str, end_str: str):
    start = datetime.strptime(start_str, "%Y-%m-%d").date()
    end   = datetime.strptime(end_str, "%Y-%m-%d").date()
    d = start
    while d <= end:
        yield d.strftime("%Y-%m-%d")
        d += timedelta(days=1)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python backfill_results.py START_DATE END_DATE")
        print("Example: python backfill_results.py 2026-06-28 2026-07-03")
        sys.exit(1)

    start_date, end_date = sys.argv[1], sys.argv[2]

    for date_str in daterange(start_date, end_date):
        print(f"\n{'='*55}")
        run(date_str)

    print(f"\n{'='*55}")
    print("Backfill complete.")
