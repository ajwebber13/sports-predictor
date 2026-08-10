"""
find_model_uncertainty.py

Root-cause fix for the sim overconfidence gap (90-99% band predicted
93.9%, actually won 48.4%).

WHY THIS WORKS WITHOUT RE-RUNNING THE FULL MONTE CARLO
--------------------------------------------------------
enhanced_predictor.py's sim draws scores_a ~ N(exp_a, std^2),
scores_b ~ N(exp_b, std^2), and computes win_prob_a as
P(scores_a > scores_b) = Phi(margin / (std*sqrt(2))), where
margin = exp_a - exp_b and Phi is the normal CDF.

That treats exp_a/exp_b (your ratings model's point estimate) as
exactly correct. It isn't — the ratings math has its own error. Adding
a second variance term (model uncertainty, mu) for "how wrong could
our rating estimate itself be" is mathematically equivalent to just
widening the effective std:

    new_win_prob = Phi( Phi^-1(old_win_prob) * std / sqrt(std^2 + mu^2) )

This lets us recompute what every historical prediction WOULD have
been under any candidate mu, using only the model_prob you already
have stored — no need to reconstruct exp_a/exp_b or re-run 10,000
simulations per game. We grid-search mu per sport, scoring each
candidate against real outcomes (Brier score), and pick the mu that
actually minimizes error.

SCOPE
-----
This applies to moneyline win probability only — spread cover-prob
and over/under prob depend on the line itself and don't reduce to
this same closed-form shrinkage. Run this first since moneyline is
the cleanest signal; extend to spread/total afterward if it helps.

Only sports using enhanced_predictor.py's normal-CDF sim apply here:
CFB, NFL, WNBA (net-rating fallback), NBA. MLB uses a separate
negative-binomial sim (mlb_predictor.py) — not covered by this script.

USAGE
-----
    python find_model_uncertainty.py
"""

import numpy as np
from scipy.stats import norm
from dotenv import load_dotenv

load_dotenv()

from database import get_conn
from predictor import CFB_CONSTANTS, NFL_CONSTANTS, NBA_CONSTANTS

# Map predictions.sport values to their score_std_dev.
# WNBA uses wnba_predictor.py's own SCORE_STD_DEV (10.5) — the real
# live model — NOT predictor.py's WNBA_CONSTANTS (10.0), which belongs
# to enhanced_predictor.py's engine and is confirmed NOT what actually
# runs WNBA predictions (see model_connector.py / routes_wnba.py).
# CFB/NFL/NBA still point at predictor.py since those DO run through
# enhanced_predictor.py.
SPORT_STD = {
    "cfb":  CFB_CONSTANTS["score_std_dev"],
    "nfl":  NFL_CONSTANTS["score_std_dev"],
    "wnba": 10.5,   # wnba_predictor.py's SCORE_STD_DEV, not predictor.py's WNBA_CONSTANTS
    "nba":  NBA_CONSTANTS["score_std_dev"],
}

MU_GRID = np.arange(0.0, 20.5, 0.5)  # candidate model-uncertainty values to test, in points


def _fetch_graded(sport: str):
    """Moneyline picks only — this shrinkage formula is for win_prob, not cover/total."""
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT p.model_prob, r.correct
        FROM results r
        JOIN predictions p ON r.prediction_id = p.id
        WHERE p.sport = ?
          AND p.market = 'moneyline'
          AND p.model_prob IS NOT NULL
          AND r.correct IS NOT NULL
        """,
        (sport,),
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        return np.array([]), np.array([])

    probs = np.array([r[0] if r[0] <= 1 else r[0] / 100 for r in rows])
    outcomes = np.array([int(r[1]) for r in rows])
    return probs, outcomes


def shrink_prob(old_prob: np.ndarray, std: float, mu: float) -> np.ndarray:
    """Re-derive win_prob under a widened effective variance (std^2 + mu^2)."""
    p = np.clip(old_prob, 0.001, 0.999)
    z = norm.ppf(p)
    z_new = z * std / np.sqrt(std**2 + mu**2)
    return norm.cdf(z_new)


def brier(probs: np.ndarray, outcomes: np.ndarray) -> float:
    return float(np.mean((probs - outcomes) ** 2))


def main():
    print("=" * 70)
    print("  Model Uncertainty Grid Search (per sport)")
    print("=" * 70)

    best_mus = {}

    for sport, std in SPORT_STD.items():
        probs, outcomes = _fetch_graded(sport)
        n = len(probs)

        if n < 30:
            print(f"\n[{sport}] only {n} moneyline picks — too few to trust a fit. Skipping.")
            continue

        baseline_brier = brier(probs, outcomes)
        results = []
        for mu in MU_GRID:
            shrunk = shrink_prob(probs, std, mu)
            results.append((mu, brier(shrunk, outcomes)))

        best_mu, best_brier = min(results, key=lambda x: x[1])

        print(f"\n[{sport}]  (n={n}, std={std})")
        print(f"  mu=0 (no fix) Brier: {baseline_brier:.4f}")
        print(f"  best mu: {best_mu:.1f}  ->  Brier: {best_brier:.4f}  (improvement: {baseline_brier - best_brier:+.4f})")

        # Show the curve around the best point for sanity
        print(f"  {'mu':>6}{'Brier':>10}")
        for mu, b in results:
            if abs(mu - best_mu) <= 2.0 or mu in (0.0, MU_GRID[-1]):
                marker = "  <-- best" if mu == best_mu else ""
                print(f"  {mu:6.1f}{b:10.4f}{marker}")

        best_mus[sport] = best_mu

    print("\n" + "=" * 70)
    print("  RESULT — add these to enhanced_predictor.py")
    print("=" * 70)
    for sport, mu in best_mus.items():
        print(f'  MODEL_UNCERTAINTY["{sport}"] = {mu}')

    print("\nNOTE: fit on your full historical set — same overfitting caveat")
    print("as the calibration curve. Validate again once 2-3 more weeks of")
    print("picks grade under the new sim before fully trusting these values.")


if __name__ == "__main__":
    main()