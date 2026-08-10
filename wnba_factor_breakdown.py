"""
wnba_factor_breakdown.py — Culture & Pulse Analytics

Isolates WHICH factor (base_projection, home_court, rest, turnovers,
situational, injury, line_movement) is causing the systematic
under-projection confirmed by total_calibration_check.py. Averages
each factor's contribution across every graded WNBA game (both home
and away sides combined) so the drag is visible per-component instead
of buried in one final number.

USAGE:
    python3 wnba_factor_breakdown.py
"""

import json

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn


def fetch_factor_rows():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT pf.home_factors, pf.away_factors,
               pf.home_score_final, pf.away_score_final,
               r.home_score, r.away_score
        FROM prediction_factors pf
        JOIN results r
          ON r.sport = pf.sport
         AND r.home_team = pf.home_team
         AND r.away_team = pf.away_team
         AND r.date = substr(pf.game_id, 1, 10)
        WHERE pf.sport = 'wnba'
          AND r.home_score IS NOT NULL
          AND r.away_score IS NOT NULL
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def main():
    rows = fetch_factor_rows()
    print(f"Found {len(rows)} graded WNBA games with factor data\n")
    if not rows:
        return

    # Collect every named factor value across both home and away sides
    factor_totals = {}
    factor_counts = {}

    total_actual_pts = 0.0
    total_projected_pts = 0.0
    n_sides = 0

    for r in rows:
        for side_factors_key, score_final_key, actual_score_key in [
            ("home_factors", "home_score_final", "home_score"),
            ("away_factors", "away_score_final", "away_score"),
        ]:
            raw = r[side_factors_key]
            factors = raw if isinstance(raw, dict) else json.loads(raw)
            for k, v in factors.items():
                if isinstance(v, (int, float)):
                    factor_totals[k] = factor_totals.get(k, 0.0) + v
                    factor_counts[k] = factor_counts.get(k, 0) + 1
            total_projected_pts += float(r[score_final_key])
            total_actual_pts += float(r[actual_score_key])
            n_sides += 1

    print(f"-- Average contribution per team-side (n={n_sides} team-sides across {len(rows)} games) --\n")
    print(f"{'Factor':<20} {'Avg contribution':<20} {'N':<6}")
    for k in sorted(factor_totals, key=lambda k: -abs(factor_totals[k] / factor_counts[k])):
        avg = factor_totals[k] / factor_counts[k]
        print(f"{k:<20} {avg:+.2f}{'':<15} {factor_counts[k]}")

    sum_of_avgs = sum(factor_totals[k] / factor_counts[k] for k in factor_totals)
    print(f"\nSum of average factors (should ≈ average projected score per side): {sum_of_avgs:.2f}")

    avg_projected = total_projected_pts / n_sides
    avg_actual = total_actual_pts / n_sides
    print(f"Average projected score per team-side: {avg_projected:.2f}")
    print(f"Average ACTUAL score per team-side:    {avg_actual:.2f}")
    print(f"Gap: {avg_projected - avg_actual:+.2f}")
    print(f"\nIf 'base_projection' alone is already far below the actual average,")
    print(f"the bug is in the off/def rating or pace math itself. If base_projection")
    print(f"looks reasonable but the OTHER factors sum to a large negative number,")
    print(f"one or more adjustments (rest/turnovers/situational/injury/line) is")
    print(f"overtuned and dragging every game down on top of a fine base.")


if __name__ == "__main__":
    main()
