"""
edge_finder_results.py — Culture & Pulse Analytics
====================================================
Checks logged Edge Finder picks (edge_finder_picks — see
edge_finder_picks_schema.sql) against real graded results
(prop_results) and reports win % / ROI, broken out by confidence
tier and by edge-score bucket.

This is the actual validation step for the whole feature: everything
built so far (engine, tests, API, dashboard, alert) proves the code
runs correctly. This is the only piece that can answer "is the ranking
actually finding profitable edges" — the question the build was
started to answer in the first place.

WHAT THIS DOES NOT DO (yet):
  Closing line movement (CLV) is NOT included. player_props/prop_results
  only capture odds once, at fetch time (~10 AM CT) — there's no second
  capture of the closing line right before tip-off, unlike game picks
  which have log_odds()/update_closing_odds()/log_line_movement() in
  database.py. Building real CLV tracking for props would need a new
  scheduled job capturing prop lines again shortly before game time and
  a reconciliation step — a real, separate build, not something this
  script can fake from data that doesn't exist. Flagging this rather
  than shipping a CLV number that would just be wrong.

Usage:
    py edge_finder_results.py                       # all logged picks
    py edge_finder_results.py --sport wnba
    py edge_finder_results.py --start 2026-07-15 --end 2026-07-31
"""

import os
import sys
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn, rows_to_dicts

EDGE_SCORE_BUCKETS = [
    (0, 60, "< 60"),
    (60, 70, "60-69"),
    (70, 80, "70-79"),
    (80, 101, "80+"),
]


def american_payout(odds, stake: float = 1.0):
    """Real American-odds profit on a winning bet of `stake` units.
    Positive odds (+150): profit = stake * odds/100.
    Negative odds (-110): profit = stake * 100/abs(odds)."""
    if odds is None:
        return None
    return stake * odds / 100 if odds > 0 else stake * 100 / abs(odds)


def fetch_graded_picks(sport: str = None, start: str = None, end: str = None) -> list:
    """Joins edge_finder_picks to prop_results on (date, sport,
    player_name, stat). Picks with no matching prop_results row yet
    are returned with hit=None (game not played/graded yet) rather
    than being silently dropped, so the report can show them as
    PENDING instead of just undercounting."""
    conn = get_conn()
    c = conn.cursor()
    query = """
        SELECT
            ep.date, ep.sport, ep.player_name, ep.stat, ep.line, ep.direction,
            ep.edge_score, ep.confidence, ep.hit_rate_overall, ep.games_overall,
            ep.projection_edge_pct, ep.defense_factor,
            pr.hit, pr.actual_value, pr.over_odds, pr.under_odds
        FROM edge_finder_picks ep
        LEFT JOIN prop_results pr
            ON ep.date = pr.date AND ep.sport = pr.sport
            AND ep.player_name = pr.player_name AND ep.stat = pr.stat
        WHERE 1=1
    """
    params = []
    if sport:
        query += " AND ep.sport = ?"
        params.append(sport)
    if start:
        query += " AND ep.date >= ?"
        params.append(start)
    if end:
        query += " AND ep.date <= ?"
        params.append(end)

    c.execute(query, params)
    rows = rows_to_dicts(c, c.fetchall())
    conn.close()
    return rows


def _bucket_label(edge_score: float) -> str:
    for lo, hi, label in EDGE_SCORE_BUCKETS:
        if lo <= edge_score < hi:
            return label
    return "unknown"


def summarize(rows: list, group_key) -> list:
    """Groups graded (non-pending) rows by group_key(row), computes
    record/win%/profit units/ROI% per group using real American-odds
    payout on the odds for whichever direction was actually picked."""
    groups = {}
    for r in rows:
        if r["hit"] is None:
            continue  # pending, not graded yet — excluded from win%/ROI
        key = group_key(r)
        groups.setdefault(key, {"wins": 0, "losses": 0, "profit": 0.0, "staked": 0.0})
        odds = r["over_odds"] if r["direction"] == "over" else r["under_odds"]
        won = r["hit"] == 1
        groups[key]["staked"] += 1.0
        if won:
            groups[key]["wins"] += 1
            payout = american_payout(odds, stake=1.0)
            groups[key]["profit"] += payout if payout is not None else 0.0
        else:
            groups[key]["losses"] += 1
            groups[key]["profit"] -= 1.0

    summary = []
    for key, g in groups.items():
        total = g["wins"] + g["losses"]
        win_pct = round(g["wins"] / total * 100, 1) if total else 0.0
        roi_pct = round(g["profit"] / g["staked"] * 100, 1) if g["staked"] else 0.0
        summary.append({
            "group": key, "wins": g["wins"], "losses": g["losses"],
            "win_pct": win_pct, "profit_units": round(g["profit"], 2), "roi_pct": roi_pct,
        })
    return summary


def print_report(rows: list):
    pending = sum(1 for r in rows if r["hit"] is None)
    graded = len(rows) - pending

    print(f"\n{'='*55}")
    print(f"  Edge Finder Results — {len(rows)} logged picks ({graded} graded, {pending} pending)")
    print(f"{'='*55}\n")

    if graded == 0:
        print("No graded picks yet — nothing to report until games are played and scored.")
        return

    print("-- Overall --")
    for row in summarize(rows, lambda r: "all"):
        print(f"  {row['wins']}-{row['losses']} ({row['win_pct']}%)  "
              f"{row['profit_units']:+.2f}u  ROI {row['roi_pct']:+.1f}%")

    print("\n-- By Confidence --")
    for row in sorted(summarize(rows, lambda r: r["confidence"]), key=lambda x: x["group"]):
        print(f"  {row['group']:<8} {row['wins']}-{row['losses']} ({row['win_pct']}%)  "
              f"{row['profit_units']:+.2f}u  ROI {row['roi_pct']:+.1f}%")

    print("\n-- By Edge Score Bucket --")
    bucket_order = [b[2] for b in EDGE_SCORE_BUCKETS]
    bucket_rows = summarize(rows, lambda r: _bucket_label(r["edge_score"]))
    bucket_rows.sort(key=lambda x: bucket_order.index(x["group"]) if x["group"] in bucket_order else 99)
    for row in bucket_rows:
        print(f"  {row['group']:<8} {row['wins']}-{row['losses']} ({row['win_pct']}%)  "
              f"{row['profit_units']:+.2f}u  ROI {row['roi_pct']:+.1f}%")

    print(
        "\nNote: closing line movement isn't tracked yet — odds are only captured "
        "once, at fetch time. See module docstring for what a real CLV build would need.\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default=None, choices=["wnba", "mlb", "nba", "nfl"])
    parser.add_argument("--start", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--end", metavar="YYYY-MM-DD", default=None)
    args = parser.parse_args()

    rows = fetch_graded_picks(sport=args.sport, start=args.start, end=args.end)
    print_report(rows)
