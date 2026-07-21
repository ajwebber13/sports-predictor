#!/usr/bin/env python3
"""
run_diagnostics.py

Runs threshold_sweep.py and tier_discrepancy_check.py back to back against
the live DB and saves the combined output to a timestamped report file, so
you have a record of each run as you iterate on thresholds/schema fixes.

Usage:
    export DATABASE_URL="postgresql://user:pass@host:port/dbname"
    python run_diagnostics.py

Requires: psycopg2-binary
    pip install psycopg2-binary
"""

import io
import os
import sys
from contextlib import redirect_stdout
from datetime import datetime

import threshold_sweep
import tier_discrepancy_check


def run_and_capture(label, main_fn):
    buf = io.StringIO()
    print(f"\n{'='*60}\n{label}\n{'='*60}")
    try:
        with redirect_stdout(buf):
            main_fn()
    except Exception as e:
        buf.write(f"\n[ERROR] {label} failed: {e}\n")
    output = buf.getvalue()
    print(output)
    return output


def main():
    if not os.environ.get("DATABASE_URL"):
        sys.exit("Set DATABASE_URL env var before running.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f"diagnostics_report_{ts}.txt"

    sections = []
    sections.append(run_and_capture("THRESHOLD SWEEP", threshold_sweep.main))
    sections.append(run_and_capture("TIER / HIT-RATE DISCREPANCY CHECK", tier_discrepancy_check.main))

    with open(report_path, "w") as f:
        f.write(f"Diagnostics run {ts}\n")
        f.write("\n".join(sections))

    print(f"\nSaved full report to {report_path}")


if __name__ == "__main__":
    main()
