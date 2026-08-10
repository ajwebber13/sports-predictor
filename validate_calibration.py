"""
validate_calibration.py

Proves the calibration fit actually helps before you wire it into
live alerts. Pulls the same graded picks calibration_transform.py
trained on, applies the saved calibration_maps.pkl, and recomputes
Brier score + ECE on the corrected probabilities. Compares directly
against the raw (uncalibrated) numbers.

This is NOT testing on new data — it's confirming the curve fits the
data it was trained on. That's expected to look good almost by
definition. The real test is running this again in 2-3 weeks against
NEW graded picks the curve has never seen. Do that before fully
trusting it long-term.

USAGE
-----
    python validate_calibration.py

Requires calibration_maps.pkl to already exist (run
calibration_transform.py --fit first).
"""

import pickle
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

from database import get_conn

CALIBRATION_FILE = Path(__file__).parent / "calibration_maps.pkl"
MARKETS = ["moneyline", "spread", "total"]


def _fetch_graded(market: str):
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


def brier_score(probs: np.ndarray, outcomes: np.ndarray) -> float:
    return float(np.mean((probs - outcomes) ** 2))


def expected_calibration_error(probs: np.ndarray, outcomes: np.ndarray, n_bins: int = 10) -> float:
    """Standard 10-bin ECE: weighted average gap between predicted and actual per bin."""
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    n = len(probs)

    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask = (probs >= lo) & (probs < hi) if i < n_bins - 1 else (probs >= lo) & (probs <= hi)
        bin_n = mask.sum()
        if bin_n == 0:
            continue
        bin_pred = probs[mask].mean()
        bin_actual = outcomes[mask].mean()
        ece += (bin_n / n) * abs(bin_pred - bin_actual)

    return float(ece)


def main():
    if not CALIBRATION_FILE.exists():
        print("No calibration_maps.pkl found — run calibration_transform.py --fit first.")
        return

    with open(CALIBRATION_FILE, "rb") as f:
        maps = pickle.load(f)

    print("=" * 70)
    print("  Calibration Validation — Before vs After")
    print("=" * 70)

    overall_raw_probs = []
    overall_raw_outcomes = []
    overall_cal_probs = []

    for market in MARKETS:
        raw_probs, outcomes = _fetch_graded(market)
        n = len(raw_probs)

        if n == 0:
            print(f"\n[{market}] no graded picks found, skipping")
            continue

        iso = maps.get(market)
        if iso is None:
            print(f"\n[{market}] no calibration curve fitted (not enough samples), skipping")
            continue

        cal_probs = iso.predict(raw_probs)

        raw_brier = brier_score(raw_probs, outcomes)
        cal_brier = brier_score(cal_probs, outcomes)
        raw_ece = expected_calibration_error(raw_probs, outcomes)
        cal_ece = expected_calibration_error(cal_probs, outcomes)

        print(f"\n[{market}]  (n={n})")
        print(f"  {'':12}{'Brier':>10}{'ECE':>10}")
        print(f"  {'Raw':12}{raw_brier:10.4f}{raw_ece:10.4f}")
        print(f"  {'Calibrated':12}{cal_brier:10.4f}{cal_ece:10.4f}")
        improved = "IMPROVED" if cal_brier < raw_brier and cal_ece < raw_ece else "NO IMPROVEMENT — investigate"
        print(f"  -> {improved}")

        overall_raw_probs.extend(raw_probs)
        overall_raw_outcomes.extend(outcomes)
        overall_cal_probs.extend(cal_probs)

    if overall_raw_probs:
        raw_arr = np.array(overall_raw_probs)
        cal_arr = np.array(overall_cal_probs)
        out_arr = np.array(overall_raw_outcomes)

        print("\n" + "=" * 70)
        print("  OVERALL (all markets combined)")
        print("=" * 70)
        print(f"  {'':12}{'Brier':>10}{'ECE':>10}")
        print(f"  {'Raw':12}{brier_score(raw_arr, out_arr):10.4f}{expected_calibration_error(raw_arr, out_arr):10.4f}")
        print(f"  {'Calibrated':12}{brier_score(cal_arr, out_arr):10.4f}{expected_calibration_error(cal_arr, out_arr):10.4f}")

    print("\nNOTE: this validates against the SAME data the curve was fit on.")
    print("Re-run this in 2-3 weeks against newly graded picks before fully")
    print("trusting it long-term — that's the real out-of-sample test.")


if __name__ == "__main__":
    main()
