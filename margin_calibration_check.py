"""
margin_calibration_check.py — Culture & Pulse Analytics

Diagnoses WHY win/cover probability (margin-based) can be miscalibrated
while total (sum-based) is fine, even though both come from the same
Monte Carlo simulation. Compares the model's projected margin (from
prediction_factors.home_score_final/away_score_final) against the real
final margin (from results.home_score/away_score) for graded games.

Two things this checks:
  1. BIAS — is the average (projected - actual) margin near zero, or
     does it lean consistently toward home or away? A real, systematic
     bias here would explain overconfident win/cover probabilities
     directly (the model thinks one side wins by more than it really
     does, on average).
  2. NOISE vs SIGNAL — correlation between projected and actual margin.
     Low correlation with low bias means the model isn't systematically
     wrong, it's just noisy — a different fix (shrink confidence toward
     50%, i.e. calibration remapping) than a biased model (fix the
     underlying math).

Works for any sport already logged via save_prediction_factors()
(mlb_predictor.py, wnba_predictor.py, etc.) — join key is
(sport, home_team, away_team, date), matching prediction_factors'
date-prefixed game_id against results.date.

USAGE:
    python3 margin_calibration_check.py --sport mlb
    python3 margin_calibration_check.py --sport wnba
"""

import sys
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn


def fetch_margin_pairs(sport: str):
    """Joins prediction_factors to results on (sport, home_team,
    away_team, date-prefix-of-game_id). Returns list of dicts with
    projected_margin, actual_margin, home_team, away_team, date."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT
            pf.home_team, pf.away_team,
            pf.home_score_final, pf.away_score_final,
            r.home_score, r.away_score, r.date
        FROM prediction_factors pf
        JOIN results r
          ON r.sport = pf.sport
         AND r.home_team = pf.home_team
         AND r.away_team = pf.away_team
         AND r.date = substr(pf.game_id, 1, 10)
        WHERE pf.sport = ?
          AND r.home_score IS NOT NULL
          AND r.away_score IS NOT NULL
    """, (sport,))
    rows = c.fetchall()
    conn.close()

    out = []
    for r in rows:
        home_final = float(r["home_score_final"])
        away_final = float(r["away_score_final"])
        home_actual = float(r["home_score"])
        away_actual = float(r["away_score"])
        proj_margin = home_final - away_final
        actual_margin = home_actual - away_actual
        out.append({
            "home_team": r["home_team"], "away_team": r["away_team"],
            "date": r["date"],
            "projected_margin": proj_margin, "actual_margin": actual_margin,
            "error": proj_margin - actual_margin,  # positive = overprojected home / underprojected away
        })
    return out


def _pearson(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


def analyze(rows, sport_label):
    print(f"\n{'='*60}")
    print(f"  Margin Calibration Check — {sport_label}")
    print(f"  {len(rows)} graded games with matched prediction_factors")
    print(f"{'='*60}\n")

    if len(rows) < 5:
        print("  Not enough matched rows to say anything meaningful.\n")
        return

    errors = [r["error"] for r in rows]
    n = len(errors)
    mean_error = sum(errors) / n
    variance = sum((e - mean_error) ** 2 for e in errors) / n
    std_error = variance ** 0.5

    mean_abs_error = sum(abs(e) for e in errors) / n

    projs = [r["projected_margin"] for r in rows]
    actuals = [r["actual_margin"] for r in rows]
    corr = _pearson(projs, actuals)

    print(f"-- Bias --")
    print(f"  Mean error (projected - actual): {mean_error:+.2f} runs/points")
    print(f"  Std dev of error: {std_error:.2f}")
    if abs(mean_error) < 0.3 * std_error:
        print("  Bias is small relative to noise — model isn't systematically")
        print("  favoring one side, errors look roughly symmetric.")
    elif mean_error > 0:
        print("  Positive bias — model systematically OVER-projects home margin")
        print("  (or under-projects away) — home side looks stronger than it is.")
    else:
        print("  Negative bias — model systematically OVER-projects away margin")
        print("  (or under-projects home) — away side looks stronger than it is.")

    print(f"\n-- Signal vs Noise --")
    print(f"  Mean absolute error: {mean_abs_error:.2f} runs/points")
    print(f"  Correlation(projected margin, actual margin): "
          f"{round(corr, 3) if corr is not None else 'N/A'}")
    if corr is not None:
        if corr >= 0.5:
            print("  Meaningful positive correlation — model has real signal,")
            print("  errors are more likely noise than a broken relationship.")
        elif corr >= 0.2:
            print("  Weak correlation — model has some signal but a lot of noise.")
        else:
            print("  Very low/no correlation — projected margin barely tracks")
            print("  actual outcomes. This is a bigger problem than calibration —")
            print("  it suggests the projection itself isn't predictive, and no")
            print("  amount of remapping win_prob will fix that.")

    # Split by whether the model favored home or away, check for a
    # directional pattern (e.g. does it overrate whichever side it likes?)
    home_favored = [r for r in rows if r["projected_margin"] > 0]
    away_favored = [r for r in rows if r["projected_margin"] < 0]
    if home_favored:
        hf_bias = sum(r["error"] for r in home_favored) / len(home_favored)
        print(f"\n  When model favored HOME (n={len(home_favored)}): "
              f"avg error {hf_bias:+.2f}")
    if away_favored:
        af_bias = sum(r["error"] for r in away_favored) / len(away_favored)
        print(f"  When model favored AWAY (n={len(away_favored)}): "
              f"avg error {af_bias:+.2f}")
    if home_favored and away_favored:
        hf_over = sum(1 for r in home_favored if r["error"] > 0) / len(home_favored) * 100
        af_over = sum(1 for r in away_favored if r["error"] < 0) / len(away_favored) * 100
        print(f"  Home-favored picks overprojected home {hf_over:.0f}% of the time")
        print(f"  Away-favored picks overprojected away {af_over:.0f}% of the time")
        if hf_over > 60 and af_over > 60:
            print("  -> Model tends to overrate WHICHEVER side it favors —")
            print("     classic overconfidence pattern, not a home/away-specific bias.")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True)
    args = parser.parse_args()

    rows = fetch_margin_pairs(args.sport.lower())
    analyze(rows, args.sport.upper())