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

CLV (calculate_clv) reconciles results -> predictions -> odds_history
to compare odds_at_pick against the real captured closing line. Only
covers picks made after get_line_movement_adj()/update_closing_odds()
went live — historical picks before that table existed will show as
skipped_no_clv, not backfilled or guessed.

Deliberately still deferred, not built here yet:
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
from services.odds_parser import american_to_implied


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


def calculate_clv(date: str = None, date_range: tuple = None, sport: str = None) -> dict:
    """
    Real Closing Line Value — the reconciliation deferred since v1.1.

    CLV answers: did we get a better price than the market eventually
    settled on? Positive CLV means our odds_at_pick implied a LOWER
    probability than the closing line did for the same side — i.e.
    the market moved toward us after we bet, which is the strongest
    evidence a model is finding real value (independent of whether
    any individual bet actually won).

    Requires three joins: results (our pick + outcome) -> predictions
    (which team we actually picked, via predicted_winner) ->
    odds_history (the real closing line for that matchup, via
    update_closing_odds()). Picks missing any piece are excluded from
    the average and counted in picks_skipped_no_clv — never guessed
    or defaulted, same principle as picks_skipped_no_odds in
    calculate_roi().

    Deliberately its own function rather than folding the join
    straight into calculate_roi() — CLV is meaningful on far fewer
    picks than ROI (needs a captured closing line, which not every
    graded pick will have), so conflating the two counts would
    understate ROI's sample size for no reason.
    """
    conn = get_conn()
    c = conn.cursor()
    where, params = _date_filter_sql(date, date_range)
    where = where.replace("date", "r.date")  # qualify against the join
    if sport:
        where += " AND r.sport = ?"
        params.append(sport)

    c.execute(f"""
        SELECT r.correct, r.odds_at_pick, r.home_team, r.away_team,
               p.predicted_winner,
               oh.closing_home_ml, oh.closing_away_ml
        FROM results r
        LEFT JOIN predictions p ON r.prediction_id = p.id
        LEFT JOIN odds_history oh
            ON oh.date = r.date AND oh.sport = r.sport
            AND oh.home_team = r.home_team AND oh.away_team = r.away_team
        WHERE {where} AND r.correct IS NOT NULL
    """, params)
    rows = c.fetchall()
    conn.close()

    clv_values = []
    skipped = 0

    for r in rows:
        picked_team = r["predicted_winner"]
        home_team   = r["home_team"]
        away_team   = r["away_team"]
        odds_at_pick = r["odds_at_pick"]
        closing_home = r["closing_home_ml"]
        closing_away = r["closing_away_ml"]

        if not picked_team or odds_at_pick is None:
            skipped += 1
            continue

        if picked_team == home_team:
            closing_ml = closing_home
        elif picked_team == away_team:
            closing_ml = closing_away
        else:
            # predicted_winner doesn't match either team name exactly
            # — a real data inconsistency, not something to guess past.
            skipped += 1
            continue

        if closing_ml is None:
            # No closing line captured for this game (e.g. noon retry
            # never ran, or game wasn't tracked that day) — skip, not zero.
            skipped += 1
            continue

        pick_implied  = american_to_implied(odds_at_pick)
        close_implied = american_to_implied(closing_ml)
        clv_pct = round((close_implied - pick_implied) * 100, 2)
        clv_values.append(clv_pct)

    if not clv_values:
        return {"avg_clv_pct": None, "picks_used": 0, "picks_skipped_no_clv": skipped}

    return {
        "avg_clv_pct": round(sum(clv_values) / len(clv_values), 2),
        "picks_used": len(clv_values),
        "picks_skipped_no_clv": skipped,
    }


def calculate_record(date: str = None, date_range: tuple = None, sport: str = None) -> dict:
    """Wins/losses/win_rate. Excludes rows where correct IS NULL (no
    result yet, or no ESPN match found by auto_results.py). Pass
    neither date nor date_range for an all-time (season) total."""
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
    1 flat unit risked per pick (see module docstring — real unit-sizing
    is a v2 schema addition, not guessed here). Picks with no odds_at_pick
    on record are excluded from the ROI count entirely rather than
    assumed at -110, since that would silently misstate the number.

    Returns "profit_units" (not "units") deliberately — once unit_size/
    stake_amount/bankroll exist, "units" alone would be ambiguous
    between "units risked" and "units profited"."""
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

    clv = calculate_clv(date=date, date_range=date_range, sport=sport)

    if not graded_with_odds:
        return {"units_risked": 0, "profit_units": 0.0, "roi_pct": None, "picks_used": 0,
                "picks_skipped_no_odds": skipped_no_odds, "clv": clv}

    total_profit = 0.0
    for r in graded_with_odds:
        total_profit += _american_profit(r["odds_at_pick"], won=(r["correct"] == 1))

    units_risked = len(graded_with_odds)
    roi_pct = round(total_profit / units_risked * 100, 1)

    return {
        "units_risked": units_risked,
        "profit_units": round(total_profit, 2),
        "roi_pct": roi_pct,
        "picks_used": len(graded_with_odds),
        "picks_skipped_no_odds": skipped_no_odds,
        "clv": clv,
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


def calculate_confidence_buckets(date: str = None, date_range: tuple = None, sport: str = None) -> list:
    """Model calibration check: does 90%+ confidence actually win ~90%
    of the time? Joins results to predictions via the existing
    prediction_id FK (already on the results table from the pre-
    regression schema — no new columns needed) to pull model_prob per
    graded pick, then buckets. A model claiming 90% and landing at 65%
    is broken — this is how you'd catch that.

    sport param added for the per-sport calibration audit — pass None
    to pool all sports together (original v1.1 behavior, unchanged)."""
    conn = get_conn()
    c = conn.cursor()
    where, params = _date_filter_sql(date, date_range)
    where = where.replace('date', 'r.date')
    if sport:
        where += " AND r.sport = ?"
        params.append(sport)
    c.execute(f"""
        SELECT r.correct, p.model_prob
        FROM results r
        JOIN predictions p ON r.prediction_id = p.id
        WHERE {where} AND r.correct IS NOT NULL AND p.model_prob IS NOT NULL
    """, params)
    rows = c.fetchall()
    conn.close()

    buckets = [
        ("90%+", 90, 100.01),
        ("85-89%", 85, 90),
        ("80-84%", 80, 85),
        ("75-79%", 75, 80),
        ("<75%", 0, 75),
    ]
    out = []
    for label, lo, hi in buckets:
        in_bucket = [r for r in rows if lo <= r["model_prob"] < hi]
        if not in_bucket:
            continue
        wins = sum(1 for r in in_bucket if r["correct"] == 1)
        total = len(in_bucket)
        out.append({
            "bucket": label, "total": total, "wins": wins, "losses": total - wins,
            "actual_win_rate": round(wins / total * 100, 1),
        })
    return out


def get_best_worst_pick(date: str = None, date_range: tuple = None) -> dict:
    """
    best/worst = highest edge_at_pick among wins/losses respectively
    (the "worst beat" — a strong pick that still lost).

    highest_confidence_pick = highest edge REGARDLESS of result — a
    separate question from best/worst: "what did the model feel
    strongest about, and was that actually right?" A big-edge pick
    that lost tells you something different than a big-edge pick that
    won; best/worst alone can't distinguish "bad result" from "bad
    prediction" the way this can.
    """
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

    c.execute(f"""
        SELECT game, sport, edge_at_pick, odds_at_pick, correct
        FROM results
        WHERE {where} AND edge_at_pick IS NOT NULL
        ORDER BY edge_at_pick DESC LIMIT 1
    """, params)
    highest_confidence = c.fetchone()

    conn.close()
    return {
        "best": dict(best) if best else None,
        "worst": dict(worst) if worst else None,
        "highest_confidence_pick": dict(highest_confidence) if highest_confidence else None,
    }


def generate_daily_summary(date: str) -> dict:
    record = calculate_record(date=date)
    roi = calculate_roi(date=date)
    by_sport = calculate_record_by_sport(date=date)
    best_worst = get_best_worst_pick(date=date)
    confidence_buckets = calculate_confidence_buckets(date=date)

    return {
        "date": date,
        "record": record,
        "roi": roi,
        "by_sport": by_sport,
        "best_pick": best_worst["best"],
        "worst_pick": best_worst["worst"],
        "highest_confidence_pick": best_worst["highest_confidence_pick"],
        "confidence_buckets": confidence_buckets,
    }


def generate_weekly_summary(end_date: str) -> dict:
    end = datetime.strptime(end_date, "%Y-%m-%d")
    start = end - timedelta(days=6)
    date_range = (start.strftime("%Y-%m-%d"), end_date)

    record = calculate_record(date_range=date_range)
    roi = calculate_roi(date_range=date_range)
    by_sport = calculate_record_by_sport(date_range=date_range)
    best_worst = get_best_worst_pick(date_range=date_range)
    confidence_buckets = calculate_confidence_buckets(date_range=date_range)

    return {
        "range": date_range,
        "record": record,
        "roi": roi,
        "by_sport": by_sport,
        "best_pick": best_worst["best"],
        "worst_pick": best_worst["worst"],
        "highest_confidence_pick": best_worst["highest_confidence_pick"],
        "confidence_buckets": confidence_buckets,
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
        sign = "+" if roi["profit_units"] >= 0 else ""
        print(f"  Units:     {sign}{roi['profit_units']} profit_units ({roi['picks_used']} picks with real odds)")
        print(f"  ROI:       {sign}{roi['roi_pct']}%")
        if roi["picks_skipped_no_odds"]:
            print(f"  (skipped {roi['picks_skipped_no_odds']} graded pick(s) with no odds_at_pick on record)")

        clv = roi.get("clv") or {}
        if clv.get("avg_clv_pct") is not None:
            clv_sign = "+" if clv["avg_clv_pct"] >= 0 else ""
            print(f"  CLV:       {clv_sign}{clv['avg_clv_pct']}% avg ({clv['picks_used']} picks with a captured closing line)")
            if clv["picks_skipped_no_clv"]:
                print(f"  (skipped {clv['picks_skipped_no_clv']} graded pick(s) with no closing line on record)")
        else:
            print("  CLV:       no picks with a captured closing line this period")
    else:
        print("  Units/ROI: no picks with recorded odds this period")

    if summary.get("confidence_buckets"):
        print(f"\n  MODEL CALIBRATION")
        for b in summary["confidence_buckets"]:
            print(f"  {b['bucket']:<8} {b['wins']}-{b['losses']} ({b['actual_win_rate']}% actual)")

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
    if summary.get("highest_confidence_pick"):
        h = summary["highest_confidence_pick"]
        result_str = "WIN" if h["correct"] == 1 else "LOSS" if h["correct"] == 0 else "PENDING"
        print(f"  Highest conf: {h['game']} ({h['sport'].upper()}) — +{h['edge_at_pick']}% edge, {result_str}")

    print(f"{'='*45}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="C&P Betting Performance Tracker")
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--range", nargs=2, metavar=("START", "END"), help="Date range YYYY-MM-DD YYYY-MM-DD")
    parser.add_argument("--weekly", metavar="END_DATE", help="7-day summary ending on this date")
    parser.add_argument("--season", action="store_true", help="All-time totals, no date filter")
    parser.add_argument("--sport", default=None, help="Filter to one sport")
    args = parser.parse_args()

    if args.season:
        record = calculate_record(sport=args.sport)
        roi = calculate_roi(sport=args.sport)
        by_sport = calculate_record_by_sport()
        best_worst = get_best_worst_pick()
        confidence_buckets = calculate_confidence_buckets()
        summary = {"record": record, "roi": roi, "by_sport": by_sport,
                   "best_pick": best_worst["best"], "worst_pick": best_worst["worst"],
                   "highest_confidence_pick": best_worst["highest_confidence_pick"],
                   "confidence_buckets": confidence_buckets}
        _print_summary(summary, "C&P ALL-TIME PERFORMANCE")
    elif args.weekly:
        summary = generate_weekly_summary(args.weekly)
        _print_summary(summary, f"C&P WEEKLY PERFORMANCE — {summary['range'][0]} to {summary['range'][1]}")
    elif args.range:
        record = calculate_record(date_range=tuple(args.range), sport=args.sport)
        roi = calculate_roi(date_range=tuple(args.range), sport=args.sport)
        by_sport = calculate_record_by_sport(date_range=tuple(args.range))
        best_worst = get_best_worst_pick(date_range=tuple(args.range))
        confidence_buckets = calculate_confidence_buckets(date_range=tuple(args.range))
        summary = {"record": record, "roi": roi, "by_sport": by_sport,
                   "best_pick": best_worst["best"], "worst_pick": best_worst["worst"],
                   "highest_confidence_pick": best_worst["highest_confidence_pick"],
                   "confidence_buckets": confidence_buckets}
        _print_summary(summary, f"C&P PERFORMANCE — {args.range[0]} to {args.range[1]}")
    elif args.date:
        summary = generate_daily_summary(args.date)
        _print_summary(summary, f"C&P DAILY PERFORMANCE REPORT — {args.date}")
    else:
        print("Usage: py performance_tracker.py --date YYYY-MM-DD | --range START END | --weekly END_DATE")