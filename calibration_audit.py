"""
calibration_audit.py — Culture & Pulse Analytics
====================================================
Phase 2 of the locked platform roadmap: confidence calibration
investigation. Answers the actual question — does a 90% confidence
pick really win ~90% of the time? — with real numbers, not a hunch.

Builds on performance_tracker.calculate_confidence_buckets(), which
already found the core problem on 2026-07-11 (80-89% landing at 50%
actual win rate). This script goes further: a finer-grained reliability
curve, Brier score, Expected Calibration Error (ECE), and a check for
whether model_prob is actually just a repackaged edge_at_pick (i.e.
"confidence" and "edge" measuring the same thing under two names,
rather than confidence being an independent probability estimate).

WHAT THIS DOES NOT DO:
  Does not fix calibration. A real fix (isotonic regression / Platt
  scaling to remap raw model_prob to true probabilities, or fixing
  whatever's producing the raw number in the first place) needs this
  script's diagnosis first — you don't refit a curve you haven't
  measured. This is the measurement step.

Usage:
    py calibration_audit.py                    # all sports, all time
    py calibration_audit.py --sport wnba
    py calibration_audit.py --start 2026-07-01 --end 2026-07-15
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
from database import get_conn


def fetch_graded_predictions(sport: str = None, start: str = None, end: str = None) -> list:
    """Same join performance_tracker.calculate_confidence_buckets() uses
    (results.prediction_id -> predictions.id), extended with
    edge_at_pick for the conflation check. Real schema, not guessed —
    mirrors the exact column names performance_tracker.py already
    validated against production."""
    conn = get_conn()
    c = conn.cursor()
    query = """
        SELECT r.correct, p.model_prob, r.edge_at_pick, r.sport, r.date
        FROM results r
        JOIN predictions p ON r.prediction_id = p.id
        WHERE r.correct IS NOT NULL AND p.model_prob IS NOT NULL
    """
    params = []
    if sport:
        query += " AND r.sport = ?"
        params.append(sport)
    if start:
        query += " AND r.date >= ?"
        params.append(start)
    if end:
        query += " AND r.date <= ?"
        params.append(end)

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    # Normalize to plain dicts regardless of row-wrapper type, same
    # defensive pattern the rest of the codebase uses after the
    # dict(row)/row[key] incident.
    return [{"correct": r["correct"], "model_prob": r["model_prob"],
              "edge_at_pick": r["edge_at_pick"], "sport": r["sport"], "date": r["date"]} for r in rows]


def reliability_curve(rows: list, bucket_size: int = 10) -> list:
    """Buckets predictions by model_prob in bucket_size-point bands
    (e.g. 50-59, 60-69...) and compares average predicted probability
    to actual win rate in each. A perfectly calibrated model has
    predicted ≈ actual in every bucket. Buckets with fewer than 5
    picks are still shown but flagged low_n, since a 2-pick bucket
    swinging to 0% or 100% isn't a calibration signal, it's noise."""
    buckets = {}
    for r in rows:
        prob = r["model_prob"]
        band = int(prob // bucket_size) * bucket_size
        buckets.setdefault(band, []).append(r)

    out = []
    for band in sorted(buckets.keys()):
        bucket_rows = buckets[band]
        n = len(bucket_rows)
        avg_predicted = sum(r["model_prob"] for r in bucket_rows) / n
        actual_win_rate = sum(1 for r in bucket_rows if r["correct"] == 1) / n * 100
        out.append({
            "band": f"{band}-{band + bucket_size - 1}%",
            "n": n,
            "avg_predicted": round(avg_predicted, 1),
            "actual_win_rate": round(actual_win_rate, 1),
            "gap": round(actual_win_rate - avg_predicted, 1),
            "low_n": n < 5,
        })
    return out


def brier_score(rows: list) -> float:
    """Mean squared error between predicted probability (0-1) and
    actual outcome (0/1). 0 = perfect, 0.25 = the score you'd get by
    always guessing exactly 50%, 1.0 = maximally wrong every time.
    Lower is better. This measures overall accuracy of the
    probabilities, not just direction/ranking of picks."""
    if not rows:
        return None
    total = sum((r["model_prob"] / 100 - r["correct"]) ** 2 for r in rows)
    return round(total / len(rows), 4)


def expected_calibration_error(rows: list, bucket_size: int = 10) -> float:
    """Weighted average |actual - predicted| across buckets, weight =
    bucket size / total. Standard ECE metric. Lower is better; under
    ~0.05 (5 percentage points) is generally considered reasonably
    calibrated, above ~0.15 is a real problem."""
    curve = reliability_curve(rows, bucket_size=bucket_size)
    if not curve:
        return None
    total_n = sum(b["n"] for b in curve)
    weighted_gap = sum(abs(b["gap"]) * b["n"] for b in curve)
    return round(weighted_gap / total_n / 100, 4)  # /100 to express as a 0-1 fraction, matching Brier's scale


def _pearson_correlation(xs: list, ys: list) -> float:
    """Manual Pearson correlation (no numpy/scipy dependency) between
    two equal-length numeric lists. Returns None if either list has
    zero variance (undefined correlation, not zero)."""
    n = len(xs)
    if n < 2:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x ** 0.5 * var_y ** 0.5)


def edge_confidence_conflation_check(rows: list) -> dict:
    """Correlation between model_prob and edge_at_pick. A very high
    correlation (roughly 0.9+) is a real signal that 'confidence' isn't
    an independent probability estimate — it's just edge dressed up as
    a percentage, which would explain calibration failures: if
    model_prob = f(edge) for some near-linear f, then model_prob was
    never a real probability to begin with, and no amount of remapping
    fixes that without addressing where model_prob comes from."""
    paired = [(r["model_prob"], r["edge_at_pick"]) for r in rows if r["edge_at_pick"] is not None]
    if len(paired) < 5:
        return {"correlation": None, "n": len(paired), "note": "too few paired rows to say anything"}
    probs = [p[0] for p in paired]
    edges = [p[1] for p in paired]
    corr = _pearson_correlation(probs, edges)
    return {"correlation": round(corr, 3) if corr is not None else None, "n": len(paired)}


def prob_spread_check(rows: list) -> dict:
    """Distribution shape of model_prob itself. A model that's actually
    discriminating between high- and low-confidence games should show
    real spread. If nearly every pick clusters in a narrow band (e.g.
    everything between 78-86%), that's a sign the underlying
    probabilities are compressed toward some central value rather than
    genuinely varying game to game."""
    probs = [r["model_prob"] for r in rows]
    if not probs:
        return {}
    n = len(probs)
    mean = sum(probs) / n
    variance = sum((p - mean) ** 2 for p in probs) / n
    return {
        "min": round(min(probs), 1), "max": round(max(probs), 1),
        "mean": round(mean, 1), "std_dev": round(variance ** 0.5, 1),
        "range": round(max(probs) - min(probs), 1),
    }


def print_calibration_report(rows: list, sport_label: str = "ALL SPORTS"):
    print(f"\n{'='*60}")
    print(f"  Confidence Calibration Audit — {sport_label}")
    print(f"  {len(rows)} graded predictions with model_prob")
    print(f"{'='*60}\n")

    if not rows:
        print("  No graded predictions found for this filter.\n")
        return

    print("-- Reliability Curve (predicted vs actual, by band) --")
    print(f"  {'Band':<10} {'N':<6} {'Predicted':<11} {'Actual':<9} {'Gap':<8}")
    for b in reliability_curve(rows):
        flag = "  (low N)" if b["low_n"] else ""
        print(f"  {b['band']:<10} {b['n']:<6} {b['avg_predicted']:<11} "
              f"{b['actual_win_rate']:<9} {b['gap']:+.1f}{flag}")

    bs = brier_score(rows)
    ece = expected_calibration_error(rows)
    print(f"\n-- Summary Metrics --")
    print(f"  Brier Score: {bs}  (0=perfect, 0.25=coin-flip baseline, lower is better)")
    print(f"  Expected Calibration Error: {ece}  (>0.05 is a real problem, >0.15 is severe)")

    conflation = edge_confidence_conflation_check(rows)
    print(f"\n-- Edge/Confidence Conflation Check --")
    if conflation["correlation"] is None:
        print(f"  {conflation.get('note', 'insufficient data')}")
    else:
        print(f"  Correlation(model_prob, edge_at_pick): {conflation['correlation']}  (n={conflation['n']})")
        if abs(conflation["correlation"]) >= 0.9:
            print("  HIGH correlation — real signal that confidence may just be edge in disguise.")
        elif abs(conflation["correlation"]) >= 0.6:
            print("  Moderate correlation — worth a closer look, not conclusive on its own.")
        else:
            print("  Low correlation — confidence and edge appear to be measuring different things.")

    spread = prob_spread_check(rows)
    print(f"\n-- Probability Spread --")
    print(f"  Range: {spread['min']}% - {spread['max']}%  (spread: {spread['range']} points)")
    print(f"  Mean: {spread['mean']}%  Std Dev: {spread['std_dev']}")
    if spread["range"] < 20:
        print("  Narrow spread — possible compression toward a central value.")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default=None)
    parser.add_argument("--start", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--end", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--bucket-size", type=int, default=10)
    args = parser.parse_args()

    rows = fetch_graded_predictions(sport=args.sport, start=args.start, end=args.end)
    label = args.sport.upper() if args.sport else "ALL SPORTS"
    print_calibration_report(rows, sport_label=label)
