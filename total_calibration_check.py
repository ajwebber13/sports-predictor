"""
total_calibration_check.py — Culture & Pulse Analytics

Companion to margin_calibration_check.py, but for TOTAL scoring
instead of margin. Compares projected_total (home_score_final +
away_score_final, from prediction_factors) against actual_total
(home_score + away_score, from results) across EVERY graded game —
not just the games where a Total bet was placed.

This matters because looking only at games with a placed Total bet
is a selection-biased sample (those are specifically the games the
model was most confident/extreme about) and can make a fine model
look badly broken. This checks the full population instead.

USAGE:
    python3 total_calibration_check.py --sport wnba
    python3 total_calibration_check.py --sport mlb
"""

import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn


def fetch_total_pairs(sport: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT
            pf.home_team, pf.away_team, r.date,
            pf.home_score_final, pf.away_score_final,
            r.home_score, r.away_score
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
        proj_total = float(r["home_score_final"]) + float(r["away_score_final"])
        actual_total = float(r["home_score"]) + float(r["away_score"])
        out.append({
            "home_team": r["home_team"], "away_team": r["away_team"], "date": r["date"],
            "projected_total": proj_total, "actual_total": actual_total,
            "error": proj_total - actual_total,  # negative = model under-projected
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
    print(f"  Total Calibration Check (ALL games) — {sport_label}")
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
    pct_under = sum(1 for e in errors if e < 0) / n * 100

    projs = [r["projected_total"] for r in rows]
    actuals = [r["actual_total"] for r in rows]
    corr = _pearson(projs, actuals)

    print(f"  Mean projected total: {sum(projs)/n:.1f}")
    print(f"  Mean actual total:    {sum(actuals)/n:.1f}")
    print(f"  Mean error (projected - actual): {mean_error:+.2f}")
    print(f"  Std dev of error: {std_error:.2f}")
    print(f"  % of games UNDER-projected: {pct_under:.0f}%")
    print(f"  Correlation(projected total, actual total): "
          f"{round(corr, 3) if corr is not None else 'N/A'}")
    print()

    if abs(mean_error) >= 0.5 * std_error and pct_under >= 65:
        print("  -> Systematic under-projection across the FULL game population,")
        print("     not just the games bet on. Real bug in the base scoring formula.")
    elif abs(mean_error) < 0.3 * std_error:
        print("  -> Bias is small relative to noise across the full population.")
        print("     The earlier finding on the 6 bet games was likely selection bias")
        print("     (those were specifically the model's most extreme Under calls),")
        print("     not evidence the formula itself is broken.")
    else:
        print("  -> Some bias present, but not as extreme as the bet-only sample")
        print("     suggested. Partly real, partly selection bias.")

    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", required=True)
    args = parser.parse_args()

    rows = fetch_total_pairs(args.sport.lower())
    analyze(rows, args.sport.upper())
