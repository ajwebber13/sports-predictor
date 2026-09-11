"""
find_mlb_uncertainty.py

MLB counterpart to find_model_uncertainty.py's grid search — but MLB
can't use that script's closed-form normal-CDF shrinkage trick. That
formula assumes the sim draws scores ~ N(exp, std^2) and treats
RUN_PROJECTION_UNCERTAINTY as a second variance term that widens std
in closed form. mlb_predictor.py's sim is negative-binomial, not
normal (see find_model_uncertainty.py's own docstring, which
explicitly excludes MLB for this reason) — there's no equivalent
closed-form remap, so this script genuinely RE-RUNS simulate_game()
for every graded game at each candidate RUN_PROJECTION_UNCERTAINTY,
using that game's actual logged run projections
(prediction_factors.home_score_final/away_score_final — exactly the
home_runs_proj/away_runs_proj simulate_game() was called with live).

CALIBRATION CAVEAT — read before trusting these numbers:
routes_mlb.py's _build_bets_for_pred() applies a FITTED calibration
curve (calibration_transform.apply_calibration()) on top of the raw
simulator output before predictions.model_prob is stored — unlike
NFL/CFB/WNBA, which currently have zero graded picks so that curve is
a pass-through no-op for them (making find_model_uncertainty.py's use
of stored model_prob effectively raw for those sports). For MLB it is
NOT a no-op — model_prob in the DB is post-calibration. So this script
does NOT compare against stored model_prob; it compares RAW
re-simulated win_prob (no calibration layer) across every candidate
mu, holding "no calibration" constant so the only thing that varies
between candidates is mu itself. That's the correct experimental
control for the actual question ("does mu alone move the needle"),
but it means the mu=0.5 row here will NOT exactly match the live
production Brier/ECE (0.2865 / 0.1625 as of this run) — that gap
between raw-mu=0.5 and calibrated-production-mu=0.5 shows how much
lift the existing calibration curve is already providing on its own.

USAGE
    python find_mlb_uncertainty.py
    python find_mlb_uncertainty.py --start 2026-08-10
    python find_mlb_uncertainty.py --grid 0,0.25,0.5,0.75,1.0,1.5
"""

import argparse
import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn
import mlb_predictor
from calibration_audit import brier_score, expected_calibration_error, reliability_curve

DEFAULT_GRID = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5]
RANDOM_SEED = 42  # fixed so mu-to-mu comparisons aren't confounded by sim noise


def fetch_graded_with_projections(sport: str = "mlb", start: str = None, end: str = None) -> list:
    """Joins results -> predictions (for pick/home_team/correct) ->
    prediction_factors (for the actual home_runs_proj/away_runs_proj
    that game's live simulate_game() call used), restricted to
    moneyline — same scope restriction find_model_uncertainty.py uses,
    since this shrinkage/re-sim question is about win_prob specifically."""
    conn = get_conn()
    c = conn.cursor()
    query = """
        SELECT p.pick, p.home_team, p.away_team, r.correct, r.date,
               pf.home_score_final, pf.away_score_final
        FROM results r
        JOIN predictions p ON r.prediction_id = p.id
        JOIN prediction_factors pf
          ON pf.sport = r.sport
         AND pf.home_team = r.home_team
         AND pf.away_team = r.away_team
         AND r.date = substr(pf.game_id, 1, 10)
        WHERE r.sport = ?
          AND p.market = 'moneyline'
          AND r.correct IS NOT NULL
          AND pf.home_score_final IS NOT NULL
          AND pf.away_score_final IS NOT NULL
    """
    params = [sport]
    if start:
        query += " AND r.date >= ?"
        params.append(start)
    if end:
        query += " AND r.date <= ?"
        params.append(end)

    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return [{
        "pick": r["pick"], "home_team": r["home_team"], "away_team": r["away_team"],
        "correct": r["correct"], "date": r["date"],
        "home_runs_proj": float(r["home_score_final"]), "away_runs_proj": float(r["away_score_final"]),
    } for r in rows]


def resimulate_at_mu(games: list, mu: float, sims: int = mlb_predictor.SIMS) -> list:
    """Re-runs simulate_game() for every game at the given
    RUN_PROJECTION_UNCERTAINTY, returns rows shaped like
    calibration_audit.py expects (model_prob 0-100, correct 0/1) for
    the side that was actually picked."""
    original = mlb_predictor.RUN_PROJECTION_UNCERTAINTY
    mlb_predictor.RUN_PROJECTION_UNCERTAINTY = mu
    try:
        out = []
        for g in games:
            sim = mlb_predictor.simulate_game(g["home_runs_proj"], g["away_runs_proj"], sims=sims)
            picked_home = g["pick"] == g["home_team"]
            pick_prob = sim["home_win_prob"] if picked_home else sim["away_win_prob"]
            out.append({"model_prob": pick_prob * 100, "correct": g["correct"]})
        return out
    finally:
        mlb_predictor.RUN_PROJECTION_UNCERTAINTY = original


def bucket(rows: list, lo: int, hi: int) -> dict:
    """Pulls one band's stats out of reliability_curve() output for
    direct before/after comparison (80-89%, 90-99%)."""
    for b in reliability_curve(rows):
        if b["band"] == f"{lo}-{hi}%":
            return b
    return {"n": 0, "avg_predicted": None, "actual_win_rate": None, "gap": None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", metavar="YYYY-MM-DD", default="2026-08-10")
    parser.add_argument("--end", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--grid", default=",".join(str(v) for v in DEFAULT_GRID))
    args = parser.parse_args()
    grid = [float(v) for v in args.grid.split(",")]

    games = fetch_graded_with_projections(start=args.start, end=args.end)
    n = len(games)
    print("=" * 78)
    print("  MLB RUN_PROJECTION_UNCERTAINTY Grid Search (re-simulated, moneyline only)")
    print(f"  {n} graded picks, {args.start} onward" + (f" through {args.end}" if args.end else ""))
    print("=" * 78)
    if n < 30:
        print(f"\n  Only {n} picks — too few to trust a fit. Stopping.")
        return

    np.random.seed(RANDOM_SEED)
    results_by_mu = {}
    for mu in grid:
        rows = resimulate_at_mu(games, mu)
        bs = brier_score(rows)
        ece = expected_calibration_error(rows)
        b80 = bucket(rows, 80, 89)
        b90 = bucket(rows, 90, 99)
        results_by_mu[mu] = {"brier": bs, "ece": ece, "b80": b80, "b90": b90}

    current_prod_mu = mlb_predictor.RUN_PROJECTION_UNCERTAINTY
    print(f"\n  (current production RUN_PROJECTION_UNCERTAINTY = {current_prod_mu})")
    print(f"\n  {'mu':>6} {'Brier':>8} {'ECE':>8}   {'80-89% N':>9} {'80-89% pred':>12} {'80-89% actual':>14} {'gap':>7}   {'90-99% N':>9} {'90-99% pred':>12} {'90-99% actual':>14} {'gap':>7}")
    baseline_brier = results_by_mu[grid[0]]["brier"]
    for mu in grid:
        r = results_by_mu[mu]
        b80, b90 = r["b80"], r["b90"]
        marker = "  <-- current prod value" if abs(mu - current_prod_mu) < 1e-9 else ""
        print(f"  {mu:6.2f} {r['brier']:8.4f} {r['ece']:8.4f}   "
              f"{b80['n']:9} {str(b80['avg_predicted']):>12} {str(b80['actual_win_rate']):>14} {str(b80['gap']):>7}   "
              f"{b90['n']:9} {str(b90['avg_predicted']):>12} {str(b90['actual_win_rate']):>14} {str(b90['gap']):>7}{marker}")

    best_mu = min(grid, key=lambda m: results_by_mu[m]["brier"])
    best_brier = results_by_mu[best_mu]["brier"]
    worst_brier = max(results_by_mu[m]["brier"] for m in grid)
    brier_range = worst_brier - min(results_by_mu[m]["brier"] for m in grid)

    print(f"\n{'='*78}")
    print("  VERDICT")
    print(f"{'='*78}")
    print(f"  Best mu by Brier: {best_mu} (Brier={best_brier:.4f})")
    print(f"  Brier range across entire grid: {brier_range:.4f} "
          f"({min(results_by_mu[m]['brier'] for m in grid):.4f} - {worst_brier:.4f})")
    if brier_range < 0.01:
        print("\n  Brier barely moves across the whole 0-1.5 grid (< 0.01 spread).")
        print("  Widening the sim's own projection-uncertainty term is NOT the")
        print("  bottleneck — even tripling it from the current 0.5 doesn't")
        print("  meaningfully change calibration. The overconfidence is coming")
        print("  from somewhere else (edge/confidence conflation, corr=0.71, is")
        print("  the next thing worth checking — a high model_prob that's really")
        print("  just edge dressed up as a probability wouldn't respond to ANY")
        print("  amount of sim-variance tuning, since it was never derived from")
        print("  the sim's own spread in the first place).")
    else:
        print("\n  Brier moves meaningfully across the grid — the sim's variance")
        print("  term does have real room to help. Worth tuning further before")
        print("  looking elsewhere.")

    b80_gaps = [results_by_mu[m]["b80"]["gap"] for m in grid if results_by_mu[m]["b80"]["n"] > 0]
    b90_gaps = [results_by_mu[m]["b90"]["gap"] for m in grid if results_by_mu[m]["b90"]["n"] > 0]
    if b80_gaps:
        print(f"\n  80-89% bucket gap range across grid: {min(b80_gaps):+.1f} to {max(b80_gaps):+.1f}")
    if b90_gaps:
        print(f"  90-99% bucket gap range across grid: {min(b90_gaps):+.1f} to {max(b90_gaps):+.1f}")
    print(f"{'='*78}\n")


if __name__ == "__main__":
    main()
