"""
calibration_transform.py

Fixes the overconfidence gap found in calibration_audit.py by learning
a correction curve per market (moneyline, spread, total) from graded
history, then applying it to every new model_prob before it reaches
alerts, edge_finder, or the dashboard.

Why isotonic regression: it doesn't assume a shape (unlike Platt/logistic
scaling). It just learns "when raw model says X%, real win rate is Y%"
directly from your 445 graded picks, market by market. That matters here
because your gap is NOT linear — it gets worse the higher the confidence
(93.9% predicted -> 48.4% actual), which a straight-line fix would miss.

USAGE
-----
Step 1 (run once, then re-run weekly as more games grade):
    python calibration_transform.py --fit

    This pulls graded predictions from the database, fits one isotonic
    curve per market, and saves them to calibration_maps.pkl in the
    project root.

Step 2 (import into your pipeline):
    from calibration_transform import apply_calibration

    raw_prob = 0.82          # whatever model_connector.py produced
    market   = "moneyline"   # "moneyline" | "spread" | "total"
    fixed_prob = apply_calibration(raw_prob, market)

    Use fixed_prob everywhere downstream: edge calc, confidence shown
    in alerts, Kelly stake sizing. Do NOT use raw_prob for any of those
    once this is wired in.

WHERE TO WIRE IT IN
--------------------
Every place that currently reads `model_prob` straight from
model_connector.py needs one line added right after:
    model_prob = apply_calibration(model_prob, market)

That's routes_wnba.py, routes_nfl.py, routes_mlb.py, routes_cfb.py,
edge_finder.py, edge_finder_alert.py, edge_finder_parlay.py,
routes_props.py — anywhere model_prob feeds into an edge, alert, or
displayed confidence number.
"""

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression
from dotenv import load_dotenv

load_dotenv()

from database import get_conn

CALIBRATION_FILE = Path(__file__).parent / "calibration_maps.pkl"

MARKETS = ["moneyline", "spread", "total"]

# Below this many graded picks in a market, don't trust a fitted curve —
# fall back to raw model_prob untouched. Isotonic regression with too few
# points overfits to noise.
MIN_SAMPLES_PER_MARKET = 40


def _fetch_graded(market: str):
    """
    Pull (model_prob, actual_result) pairs for one market.
    actual_result is 1 if the pick won, 0 if it lost.
    Matches calibration_audit.py's real join: model_prob and market
    live on `predictions`, win/loss lives on `results` as `correct`
    (1/0), joined via results.prediction_id = predictions.id.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT p.model_prob, r.correct
        FROM results r
        JOIN predictions p ON r.prediction_id = p.id
        WHERE p.market = ?
          AND p.model_prob IS NOT NULL
          AND r.correct IS NOT NULL
        """,
        (market,),
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return np.array([]), np.array([])

    probs = np.array([r[0] if r[0] <= 1 else r[0] / 100 for r in rows])
    outcomes = np.array([int(r[1]) for r in rows])
    return probs, outcomes


def fit_and_save():
    """Fit one isotonic curve per market and save to disk."""
    maps = {}

    for market in MARKETS:
        probs, outcomes = _fetch_graded(market)
        n = len(probs)

        if n < MIN_SAMPLES_PER_MARKET:
            print(f"[{market}] only {n} graded picks — need {MIN_SAMPLES_PER_MARKET}+. Skipping, raw prob will pass through unchanged.")
            continue

        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.01, y_max=0.99)
        iso.fit(probs, outcomes)
        maps[market] = iso

        # Quick before/after sanity print at a few reference points
        checkpoints = [0.5, 0.6, 0.7, 0.8, 0.9]
        print(f"\n[{market}] fitted on {n} graded picks")
        print(f"  {'raw':>6}  ->  {'calibrated':>10}")
        for p in checkpoints:
            fixed = float(iso.predict([p])[0])
            print(f"  {p*100:5.0f}%  ->  {fixed*100:8.1f}%")

    with open(CALIBRATION_FILE, "wb") as f:
        pickle.dump(maps, f)

    print(f"\nSaved {len(maps)}/{len(MARKETS)} market calibration curves to {CALIBRATION_FILE}")
    if len(maps) < len(MARKETS):
        missing = set(MARKETS) - set(maps.keys())
        print(f"NOTE: {missing} not calibrated yet — raw model_prob passes through untouched for those markets until enough graded picks accumulate.")


def apply_calibration(raw_prob: float, market: str) -> float:
    """
    Apply the fitted correction to a raw model probability.

    raw_prob: 0-1 or 0-100, handles either.
    market: "moneyline" | "spread" | "total"

    Returns a 0-1 probability. If no calibration map exists yet for
    that market (not enough graded data), returns raw_prob unchanged
    so nothing breaks before the first fit.
    """
    if raw_prob > 1:
        raw_prob = raw_prob / 100

    if not CALIBRATION_FILE.exists():
        return raw_prob

    with open(CALIBRATION_FILE, "rb") as f:
        maps = pickle.load(f)

    iso = maps.get(market)
    if iso is None:
        return raw_prob

    return float(iso.predict([raw_prob])[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fit", action="store_true", help="Fit and save calibration curves from graded history")
    args = parser.parse_args()

    if args.fit:
        fit_and_save()
    else:
        print("Run with --fit to build the calibration maps first.")
        sys.exit(1)