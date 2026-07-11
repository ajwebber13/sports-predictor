"""
performance_tracker.py — Culture & Pulse Analytics
====================================================
Standalone analytics engine — the "accounting system" for C&P picks.
Deliberately kept separate from dashboard.py/pick_of_the_day.py/
database.py per the build spec: this is where performance math lives,
everything else just calls into it.

v1 scope: uses ONLY columns that already exist and are already proven
working (results.correct, results.edge_at_pick, results.odds_at_pick —
confirmed live via tonight's real scoring run). ROI is computed from
actual American odds per pick, not a flat -110 assumption.

Deliberately deferred to v2, not built here yet:
  - CLV (closing_odds lives in odds_history, not results — needs a
    real join/reconciliation pass before this can trust it)
  - units/stake sizing (no unit_size column on predictions yet —
    every pick is treated as 1 flat unit for now; real bet-sizing
    logic needs that schema addition first, not guessed here)
  - confidence-tier calibration breakdown (needs the confidence_grade
    column proposed in the spec — v1 buckets by raw model_prob instead)

Usage:
    py performance_tracker.py --date 2026-07-10
    py performance_tracker.py --date 2026-07-10 --sport mlb
    py performance_tracker.py --range 2026-07-01 2026-07-10
    py performance_tracker.py --season   # all-time
"""

import os
import sys
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn


def _american_profit(odds: int, won: bool) -> float:
    """Profit in units for a 1-unit stake at these American odds.
    Win: positive odds pay odds/100 per unit, negative odds pay
    100/abs(odds) per unit. Loss: lose the full 1-unit stake."""
    if not won:
        return -1.0
    if odds is None:
        return 0.0  # can't compute payout without real odds — excluded from ROI, not silently guessed
    if odds > 0:
        return odds / 100
    return 100 / abs(odds)


def _date_filter_sql(date: str = None, date_range: tuple = None):
    """Returns (where_clause, params) for filtering results by date."""
    if date:
        return "date = ?", [date]
    if date_range:
        return "date BETWEEN ? AND ?", [date_range[0], date_range[1]]
    return "1=1", []


def calculate_record(date: str = None, date_range: tuple = None, sport: str = None) -> dict:
    """Wins/losses/win_rate. Excludes rows where correct IS NULL (no
    result yet, or no ESPN match found by auto_results.py)."""
    conn = get_conn()
    c = conn.cursor()
    where, params = _date_filter_sql(date, date_range)
    if sport:
        where += " AND sport = ?"
        params.append(sport)
    c.execute(f"""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as wins
        FROM results
        WHERE {where} AND correct IS NOT NULL
    """, params)
    row = c.fetchone()
    conn.close()

    total = row["total"] or 0
    wins = row["wins"] or 0
    losses = total - wins
    win_rate = round(wins / total * 100, 1) if total else None

    return {"total": total, "wins": wins, "losses": losses, "win_rate": win_rate}


def calculate_roi(date: str = None, date_range: tuple = None, sport: str = None) -> dict:
    """Real ROI computed from actual odds_at_pick per graded result,
    1 flat unit per pick (see module docstring — real unit-sizing is
    a v2 schema addition, not guessed here). Picks with no odds_at_pick
    on record are excluded from the ROI count entirely rather than
    assumed at -110, since that would silently misstate the number."""
    conn = get_conn()
    c = conn.cursor()
    where, params = _date_filter_sql(date, date_range)
    if sport:
        where += " AND sport = ?"
        params.append(sport)
    c.execute(f"""
        SELECT correct, odds_at_pick
        FROM results
        WHERE {where} AND correct IS NOT NULL
    """, params)
    rows = c.fetchall()
    conn.close()

    graded_with_odds = [r for r in rows if r["odds_at_pick"] is not None]
    skipped_no_odds = len(rows) - len(graded_with_odds)

    if not graded_with_odds:
        return {"units_risked": 0, "profit": 0.0, "roi_pct": None, "picks_used": 0, "picks_skipped_no_odds": skipped_no_odds}

    total_profit = 0.0
    for r in graded_with_odds:
        total_profit += _american_profit(r["odds_at_pick"], won=(r["correct"] == 1))

    units_risked = len(graded_with_odds)
    roi_pct = round(total_profit / units_risked * 100, 1)

    return {
        "units_risked": units_risked,
        "profit": round(total_profit, 2),
        "roi_pct": roi_pct,
        "picks_used": len(graded_with_odds),
        "picks_skipped_no_odds": skipped_no_odds,
    }


def calculate_record_by_sport(date: str = None, date_range: tuple = None) -> list:
    """Same as calculate_record but broken out per sport, for the
    recap's by-sport section."""
    conn = get_conn()
    c = conn.cursor()
    where, params = _date_filter_sql(date, date_range)
    c.execute(f"""
        SELECT sport,
               COUNT(*) as total,
               SUM(CASE WHEN correct = 1 THEN 1 ELSE 0 END) as wins
        FROM results
        WHERE {where} AND correct IS NOT NULL
        GROUP BY sport
        ORDER BY total DESC
    """, params)
    rows = c.fetchall()
    conn.close()

    out = []
    for r in rows:
        total = r["total"] or 0
        wins = r["wins"] or 0
        out.append({
            "sport": r["sport"],
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total * 100, 1) if total else None,
        })
    return out


def get_best_worst_pick(date: str = None, date_range: tuple = None) -> dict:
    """Best = highest edge_at_pick among wins. Worst = highest
    edge_at_pick among losses (the pick the model was most confident
    about, that still lost — the "worst beat" from the spec)."""
    conn = get_conn()
    c = conn.cursor()
    where, params = _date_filter_sql(date, date_range)

    c.execute(f"""
        SELECT game, sport, edge_at_pick, odds_at_pick
        FROM results
        WHERE {where} AND correct = 1 AND edge_at_pick IS NOT NULL
        ORDER BY edge_at_pick DESC LIMIT 1
    """, params)
    best = c.fetchone()

    c.execute(f"""
        SELECT game, sport, edge_at_pick, odds_at_pick
        FROM results
        WHERE {where} AND correct = 0 AND edge_at_pick IS NOT NULL
        ORDER BY edge_at_pick DESC LIMIT 1
    """, params)
    worst = c.fetchone()

    conn.close()
    return {
        "best": dict(best) if best else None,
        "worst": dict(worst) if worst else None,
    }


def generate_daily_summary(date: str) -> dict:
    record = calculate_record(date=date)
    roi = calculate_roi(date=date)
    by_sport = calculate_record_by_sport(date=date)
    best_worst = get_best_worst_pick(date=date)

    return {
        "date": date,
        "record": record,
        "roi": roi,
        "by_sport": by_sport,
        "best_pick": best_worst["best"],
        "worst_pick": best_worst["worst"],
    }


def generate_weekly_summary(end_date: str) -> dict:
    end = datetime.strptime(end_date, "%Y-%m-%d")
    start = end - timedelta(days=6)
    date_range = (start.strftime("%Y-%m-%d"), end_date)

    record = calculate_record(date_range=date_range)
    roi = calculate_roi(date_range=date_range)
    by_sport = calculate_record_by_sport(date_range=date_range)
    best_worst = get_best_worst_pick(date_range=date_range)

    return {
        "range": date_range,
        "record": record,
        "roi": roi,
        "by_sport": by_sport,
        "best_pick": best_worst["best"],
        "worst_pick": best_worst["worst"],
    }


def _print_summary(summary: dict, title: str):
    print(f"\n{'='*45}")
    print(f"  {title}")
    print(f"{'='*45}")

    r = summary["record"]
    roi = summary["roi"]

    if r["total"] == 0:
        print("  No graded picks in this period.")
        print(f"{'='*45}\n")
        return

    print(f"  Record:    {r['wins']}-{r['losses']} ({r['win_rate']}% win rate)")
    if roi["roi_pct"] is not None:
        sign = "+" if roi["profit"] >= 0 else ""
        print(f"  Units:     {sign}{roi['profit']} ({roi['picks_used']} picks with real odds)")
        print(f"  ROI:       {sign}{roi['roi_pct']}%")
        if roi["picks_skipped_no_odds"]:
            print(f"  (skipped {roi['picks_skipped_no_odds']} graded pick(s) with no odds_at_pick on record)")
    else:
        print("  Units/ROI: no picks with recorded odds this period")

    if summary["by_sport"]:
        print(f"\n  BY SPORT")
        for s in summary["by_sport"]:
            print(f"  {s['sport'].upper():<8} {s['wins']}-{s['losses']} ({s['win_rate']}%)")

    if summary["best_pick"]:
        b = summary["best_pick"]
        print(f"\n  Best pick:  {b['game']} ({b['sport'].upper()}) — +{b['edge_at_pick']}% edge, WIN")
    if summary["worst_pick"]:
        w = summary["worst_pick"]
        print(f"  Worst beat: {w['game']} ({w['sport'].upper()}) — +{w['edge_at_pick']}% edge, LOSS")

    print(f"{'='*45}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="C&P Betting Performance Tracker")
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--range", nargs=2, metavar=("START", "END"), help="Date range YYYY-MM-DD YYYY-MM-DD")
    parser.add_argument("--weekly", metavar="END_DATE", help="7-day summary ending on this date")
    parser.add_argument("--sport", default=None, help="Filter to one sport")
    args = parser.parse_args()

    if args.weekly:
        summary = generate_weekly_summary(args.weekly)
        _print_summary(summary, f"C&P WEEKLY PERFORMANCE — {summary['range'][0]} to {summary['range'][1]}")
    elif args.range:
        record = calculate_record(date_range=tuple(args.range), sport=args.sport)
        roi = calculate_roi(date_range=tuple(args.range), sport=args.sport)
        by_sport = calculate_record_by_sport(date_range=tuple(args.range))
        best_worst = get_best_worst_pick(date_range=tuple(args.range))
        summary = {"record": record, "roi": roi, "by_sport": by_sport,
                   "best_pick": best_worst["best"], "worst_pick": best_worst["worst"]}
        _print_summary(summary, f"C&P PERFORMANCE — {args.range[0]} to {args.range[1]}")
    elif args.date:
        summary = generate_daily_summary(args.date)
        _print_summary(summary, f"C&P DAILY PERFORMANCE REPORT — {args.date}")
    else:
        print("Usage: py performance_tracker.py --date YYYY-MM-DD | --range START END | --weekly END_DATE")
