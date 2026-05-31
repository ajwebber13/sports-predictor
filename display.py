"""
display.py
===========
Formatted output for terminal and JSON export.
"""

import json
from predictor import GamePrediction


def print_prediction(pred: GamePrediction, compact: bool = False) -> None:
    """Full formatted prediction report."""
    W  = 62
    DV = "═" * W
    dv = "─" * W

    def row(label, a_val, b_val, pad=26):
        return f"  {label:<{pad}} {a_val:>12}  {b_val:>12}"

    print(f"\n{DV}")
    print(f"  PREDICTION: {pred.team_a_name} vs {pred.team_b_name}")
    print(f"  Monte Carlo Simulations: {pred.simulations_run:,}")
    print(DV)

    # ── Win Probability ────────────────────────────────────
    print(f"\n  {'WIN PROBABILITY':}")
    print(dv)
    print(row("", pred.team_a_name, pred.team_b_name))
    print(row("Win Prob",
              f"{pred.team_a_win_prob:.1f}%",
              f"{pred.team_b_win_prob:.1f}%"))

    # ── Projected Score ────────────────────────────────────
    print(f"\n  {'PROJECTED SCORE':}")
    print(dv)
    print(row("", pred.team_a_name, pred.team_b_name))
    print(row("Expected Pts",
              f"{pred.projected_pts_a:.1f}",
              f"{pred.projected_pts_b:.1f}"))
    print(row("Score Range (10th–90th)",
              f"{pred.score_range_a[0]:.0f}–{pred.score_range_a[1]:.0f}",
              f"{pred.score_range_b[0]:.0f}–{pred.score_range_b[1]:.0f}"))
    print(f"  {'Projected Total':<26} {pred.projected_total:.1f}")

    # ── Spread ─────────────────────────────────────────────
    print(f"\n  {'SPREAD ANALYSIS':}")
    print(dv)
    if pred.spread_line > 0:
        fav, dog = pred.team_a_name, pred.team_b_name
        fav_pts  = f"−{pred.spread_line}"
    else:
        fav, dog = pred.team_b_name, pred.team_a_name
        fav_pts  = f"−{abs(pred.spread_line)}"
    print(f"  Line: {fav} {fav_pts}  /  {dog} +{abs(pred.spread_line)}")
    print(row("Cover Prob",
              f"{pred.team_a_cover_prob:.1f}%",
              f"{pred.team_b_cover_prob:.1f}%"))

    # ── Totals ─────────────────────────────────────────────
    print(f"\n  {'OVER/UNDER':}")
    print(dv)
    print(f"  Line: {pred.over_under_line}")
    print(f"  {'Over':<26} {pred.over_prob:.1f}%")
    print(f"  {'Under':<26} {pred.under_prob:.1f}%")

    # ── Ratings ────────────────────────────────────────────
    if not compact:
        print(f"\n  {'TEAM RATINGS  (1.00 = League Avg)':}")
        print(dv)
        print(f"  {'':26} {'OFF RTG':>10}  {'DEF RTG':>10}")
        print(f"  {pred.team_a_name:<26} {pred.off_rating_a:>10.3f}  {pred.def_rating_a:>10.3f}")
        print(f"  {pred.team_b_name:<26} {pred.off_rating_b:>10.3f}  {pred.def_rating_b:>10.3f}")

    # ── Edge ───────────────────────────────────────────────
    print(f"\n  {'MARKET EDGE ANALYSIS':}")
    print(dv)
    print(f"  {'':26} {'MODEL':>8}  {'MARKET':>8}  {'EDGE':>7}  {'SIGNAL':}")
    print(f"  {pred.team_a_name:<26} "
          f"{pred.model_prob_a:>7.1f}%  "
          f"{pred.sportsbook_implied_a:>7.1f}%  "
          f"{pred.edge_a:>+7.1f}%  "
          f"{pred.edge_label(pred.edge_a)}")
    print(f"  {pred.team_b_name:<26} "
          f"{pred.model_prob_b:>7.1f}%  "
          f"{pred.sportsbook_implied_b:>7.1f}%  "
          f"{pred.edge_b:>+7.1f}%  "
          f"{pred.edge_label(pred.edge_b)}")

    print(f"\n{DV}\n")


def export_json(predictions: list[GamePrediction], filepath: str) -> None:
    """Export all predictions to JSON (for API / frontend use)."""
    data = [p.to_dict() for p in predictions]
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  ✓ Exported {len(data)} prediction(s) → {filepath}")


def print_batch_summary(predictions: list[GamePrediction]) -> None:
    """Compact summary table for multiple games."""
    W = 80
    print(f"\n{'═' * W}")
    print(f"  BATCH PREDICTIONS SUMMARY")
    print(f"{'═' * W}")
    header = f"  {'MATCHUP':<35} {'WIN A':>7} {'WIN B':>7} {'PROJ':>7} {'EDGE A':>8}"
    print(header)
    print(f"{'─' * W}")
    for p in predictions:
        matchup = f"{p.team_a_name[:16]} vs {p.team_b_name[:14]}"
        proj    = f"{p.projected_pts_a:.0f}–{p.projected_pts_b:.0f}"
        print(f"  {matchup:<35} "
              f"{p.team_a_win_prob:>6.1f}% "
              f"{p.team_b_win_prob:>6.1f}% "
              f"{proj:>7}  "
              f"{p.edge_a:>+7.1f}% {p.edge_label(p.edge_a)}")
    print(f"{'═' * W}\n")
