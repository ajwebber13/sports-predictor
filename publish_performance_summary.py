"""
publish_performance_summary.py — Culture & Pulse Analytics
====================================================
Generates a PUBLIC-SAFE performance summary JSON from performance_tracker.py's
existing functions — no new database schema, no new pipeline. This is the
"public showroom" half of the split agreed 2026-07-12: Streamlit/the database
stay the private research lab (individual picks, lines, odds, team names on
each bet); this script only ever exports AGGREGATE numbers (record, ROI,
confidence-bucket calibration) — nothing that identifies a specific pick.

Deliberately excluded from this export, on purpose, every run:
  - individual game picks (team, line, odds)
  - dates of specific bets
  - anything from `predictions` or `results` beyond aggregate counts

Output: performance-summary.json, matching the same {value, source,
confidence} + "updated" convention already used by wnba-rankings.json,
wnba-players.json, and wnba-games.json on the website. Copy this file into
cp-sports-site/data/ manually for now — this is the JSON-bridge step, same
pattern as the rankings/players/games files. A real FastAPI connection is
future work (see roadmap), not a prerequisite for showing a real record
publicly.

Usage:
    py publish_performance_summary.py
    py publish_performance_summary.py --season 2026
"""

import os
import sys
import json
import argparse
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from performance_tracker import (
    calculate_record,
    calculate_roi,
    calculate_record_by_sport,
    calculate_confidence_buckets,
)

OUTPUT_PATH = "performance-summary.json"


def build_summary(season_prefix: str = None) -> dict:
    date_range = None
    if season_prefix:
        # crude season filter reusing the same date-string-prefix trick
        # used elsewhere in the codebase (e.g. wnba_game_results.py's
        # --season) — good enough for "this calendar year", not a real
        # season-boundary concept
        date_range = (f"{season_prefix}-01-01", f"{season_prefix}-12-31")

    overall = calculate_record(date_range=date_range)
    roi = calculate_roi(date_range=date_range)
    by_sport = calculate_record_by_sport(date_range=date_range)
    confidence_buckets = calculate_confidence_buckets(date_range=date_range)

    def wrap(value):
        # Every number here comes straight out of performance_tracker.py's
        # real queries against results/predictions — genuinely "high"
        # confidence, same as elo/form/schedule_strength on the rankings
        # pages. Nothing in this file is a placeholder.
        return {"value": value, "source": "performance_tracker", "confidence": "high"}

    return {
        "entity": "performance_summary",
        "updated": date.today().isoformat(),
        "model_version": "v1.0",
        "note": ("Aggregate performance only — no individual picks, lines, "
                 "odds, or bet dates are exported here. See performance_tracker.py "
                 "for the private, full-detail source this was generated from."),
        "overall": {
            "record": wrap(f"{overall['wins']}-{overall['losses']}"),
            "win_rate_pct": wrap(overall["win_rate"]),
            "total_graded": wrap(overall["total"]),
        },
        "roi": {
            "roi_pct": wrap(roi["roi_pct"]),
            "profit_units": wrap(roi["profit_units"]),
            "picks_used": wrap(roi["picks_used"]),
            "picks_skipped_no_odds": wrap(roi["picks_skipped_no_odds"]),
            "clv": wrap(roi["clv"]),  # currently always null — see performance_tracker.py's own note
        },
        "by_sport": [
            {
                "sport": s["sport"],
                "record": wrap(f"{s['wins']}-{s['losses']}"),
                "win_rate_pct": wrap(s["win_rate"]),
            }
            for s in by_sport
        ],
        "confidence_calibration": [
            {
                "bucket": b["bucket"],
                "record": wrap(f"{b['wins']}-{b['losses']}"),
                "actual_win_rate_pct": wrap(b["actual_win_rate"]),
            }
            for b in confidence_buckets
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Publish a public-safe performance summary JSON")
    parser.add_argument("--season", default=None, help="Optional year filter, e.g. '2026'")
    args = parser.parse_args()

    summary = build_summary(season_prefix=args.season)

    with open(OUTPUT_PATH, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\nWrote {OUTPUT_PATH}")
    print(f"  Overall record: {summary['overall']['record']['value']} "
          f"({summary['overall']['win_rate_pct']['value']}%)")
    print(f"  ROI: {summary['roi']['roi_pct']['value']}%")
    print(f"  Sports covered: {len(summary['by_sport'])}")
    print(f"  Confidence buckets: {len(summary['confidence_calibration'])}")
    print("\nCopy performance-summary.json into cp-sports-site/data/ to use it on the website.")
