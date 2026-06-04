"""
enhanced_display.py
====================
Output formatter for EnhancedPrediction — shows all new signals:
  advanced metrics, ATS records, situational factors, market signals.
"""

import json
from enhanced_predictor import EnhancedPrediction
from situational import summarize_context


def print_enhanced_prediction(pred: EnhancedPrediction, compact: bool = False) -> None:
    """Full enhanced prediction report."""
    W  = 66
    DV = "═" * W
    dv = "─" * W

    def row(label, a_val, b_val, pad=28):
        return f"  {label:<{pad}} {str(a_val):>12}  {str(b_val):>12}"

    print(f"\n{DV}")
    print(f"  {pred.team_a_name} vs {pred.team_b_name}")
    print(f"  {pred.simulations_run:,} Monte Carlo simulations")
    print(DV)

    # ── Win Probability ────────────────────────────────────────
    print(f"\n  WIN PROBABILITY")
    print(dv)
    print(row("", pred.team_a_name[:14], pred.team_b_name[:14]))
    print(row("Win Prob", f"{pred.team_a_win_prob:.1f}%", f"{pred.team_b_win_prob:.1f}%"))
    print(f"  Elo Rating {'':<18} {pred.elo_a:>12.0f}  {pred.elo_b:>12.0f}")

    # ── Projected Score ────────────────────────────────────────
    print(f"\n  PROJECTED SCORE")
    print(dv)
    print(row("", pred.team_a_name[:14], pred.team_b_name[:14]))
    print(row("Expected Pts", f"{pred.projected_pts_a:.1f}", f"{pred.projected_pts_b:.1f}"))
    print(row("Score Range (10–90th)",
              f"{pred.score_range_a[0]:.0f}–{pred.score_range_a[1]:.0f}",
              f"{pred.score_range_b[0]:.0f}–{pred.score_range_b[1]:.0f}"))
    print(f"  {'Projected Total':<28} {pred.projected_total:.1f}")

    # ── Spread / Totals ────────────────────────────────────────
    print(f"\n  SPREAD  |  O/U")
    print(dv)
    if pred.spread_line > 0:
        fav, dog = pred.team_a_name, pred.team_b_name
        pts = f"-{pred.spread_line}"
    else:
        fav, dog = pred.team_b_name, pred.team_a_name
        pts = f"-{abs(pred.spread_line)}"
    print(f"  Spread: {fav} {pts}  /  {dog} +{abs(pred.spread_line)}")
    print(row("Cover Prob", f"{pred.team_a_cover_prob:.1f}%", f"{pred.team_b_cover_prob:.1f}%"))
    print(f"  O/U Line: {pred.over_under_line}   Over {pred.over_prob:.1f}%   Under {pred.under_prob:.1f}%")

    # ── Team Ratings ───────────────────────────────────────────
    print(f"\n  TEAM RATINGS  (1.00 = League Avg)")
    print(dv)
    print(f"  {'':28} {'OFF RTG':>8}  {'DEF RTG':>8}  {'EPA OFF':>8}  {'EPA DEF':>8}")
    print(f"  {pred.team_a_name:<28} {pred.off_rating_a:>8.3f}  {pred.def_rating_a:>8.3f}  {pred.epa_off_a:>+8.3f}  {pred.epa_def_a:>+8.3f}")
    print(f"  {pred.team_b_name:<28} {pred.off_rating_b:>8.3f}  {pred.def_rating_b:>8.3f}  {pred.epa_off_b:>+8.3f}  {pred.epa_def_b:>+8.3f}")

    # ── Advanced Metrics ───────────────────────────────────────
    if not compact:
        print(f"\n  ADVANCED METRICS")
        print(dv)
        print(f"  {'':28} {'SUCC OFF':>8}  {'SUCC DEF':>8}")
        print(f"  {pred.team_a_name:<28} {pred.success_off_a:>8.1%}  {pred.success_def_a:>8.1%}")
        print(f"  {pred.team_b_name:<28} {pred.success_off_b:>8.1%}  {pred.success_def_b:>8.1%}")

    # ── ATS Records ────────────────────────────────────────────
    print(f"\n  ATS RECORD  (last 3 seasons)")
    print(dv)
    ats_a = pred.ats_a
    ats_b = pred.ats_b
    if ats_a.games_rated > 0:
        print(f"  {pred.team_a_name:<28} {ats_a.overall_w}-{ats_a.overall_l}-{ats_a.overall_p}  ({ats_a.overall_pct:.1%})  {ats_a.ats_signal()}")
        print(f"  {'  Home ATS':<28} {ats_a.home_w}-{ats_a.home_l}  ({ats_a.home_pct:.1%})")
        print(f"  {'  Away ATS':<28} {ats_a.away_w}-{ats_a.away_l}  ({ats_a.away_pct:.1%})")
    else:
        print(f"  {pred.team_a_name}: No ATS data")

    if ats_b.games_rated > 0:
        print(f"  {pred.team_b_name:<28} {ats_b.overall_w}-{ats_b.overall_l}-{ats_b.overall_p}  ({ats_b.overall_pct:.1%})  {ats_b.ats_signal()}")
        print(f"  {'  Home ATS':<28} {ats_b.home_w}-{ats_b.home_l}  ({ats_b.home_pct:.1%})")
        print(f"  {'  Away ATS':<28} {ats_b.away_w}-{ats_b.away_l}  ({ats_b.away_pct:.1%})")
    else:
        print(f"  {pred.team_b_name}: No ATS data")

    # ── Situational ────────────────────────────────────────────
    print(f"\n  SITUATIONAL FACTORS")
    print(dv)
    print(summarize_context(pred.context, pred.team_a_name, pred.team_b_name))
    if pred.weather_adj != 0:
        print(f"  Weather scoring impact: {pred.weather_adj:+.1f} pts/team")
    if pred.rest_adj_a != 0 or pred.rest_adj_b != 0:
        print(f"  Rest: {pred.team_a_name} {pred.rest_adj_a:+.1f}  |  {pred.team_b_name} {pred.rest_adj_b:+.1f}")
    if pred.travel_adj_b != 0:
        print(f"  Travel penalty {pred.team_b_name}: {pred.travel_adj_b:+.1f} pts")

    # ── Market Edge ────────────────────────────────────────────
    print(f"\n  MARKET EDGE")
    print(dv)
    print(f"  {'':28} {'MODEL':>8}  {'MARKET':>8}  {'EDGE':>7}  SIGNAL")
    print(f"  {pred.team_a_name:<28} {pred.model_prob_a:>7.1f}%  {pred.sportsbook_implied_a:>7.1f}%  {pred.edge_a:>+7.1f}%  {pred.edge_label(pred.edge_a)}")
    print(f"  {pred.team_b_name:<28} {pred.model_prob_b:>7.1f}%  {pred.sportsbook_implied_b:>7.1f}%  {pred.edge_b:>+7.1f}%  {pred.edge_label(pred.edge_b)}")

    print(f"\n{DV}\n")


def print_enhanced_summary(predictions: list) -> None:
    """Compact multi-game summary table."""
    W = 90
    print(f"\n{'═'*W}")
    print(f"  ENHANCED PREDICTIONS SUMMARY")
    print(f"{'═'*W}")
    hdr = f"  {'MATCHUP':<35} {'WIN A':>7} {'WIN B':>7} {'PROJ':>8} {'EDGE A':>8}  {'ATS A':>10}  {'WEATHER'}"
    print(hdr)
    print(f"{'─'*W}")
    for p in predictions:
        matchup = f"{p.team_a_name[:16]} vs {p.team_b_name[:15]}"
        proj    = f"{p.projected_pts_a:.0f}–{p.projected_pts_b:.0f}"
        ats_a   = f"{p.ats_a.overall_pct:.0%} ATS" if p.ats_a.games_rated > 5 else "N/A"
        weather = p.context.weather_summary()[:12] if not p.context.is_dome else "DOME"
        print(f"  {matchup:<35} {p.team_a_win_prob:>6.1f}% {p.team_b_win_prob:>6.1f}% {proj:>8}  {p.edge_a:>+7.1f}%  {ats_a:>10}  {weather}")
    print(f"{'═'*W}\n")


def export_enhanced_json(predictions: list, filepath: str) -> None:
    """Export predictions to JSON."""
    data = [p.to_dict() for p in predictions]
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  ✓ Exported {len(data)} predictions → {filepath}")


def print_roster_factors(pred, team_name: str, roster) -> None:
    """Print roster factor details for one team."""
    if not roster:
        return
    W = 66
    print(f"\n  ROSTER FACTORS — {team_name.upper()}")
    print("─" * W)
    print(f"  Returning Production  {roster.returning.pct_ppa_off:.0%} returning  {roster.returning.label()}")
    print(f"  Transfer Portal       Net {roster.portal.net_score:+.1f}  off {roster.portal.off_adj:+.3f}  def {roster.portal.def_adj:+.3f}  {roster.portal.label()}")
    if roster.qb.data_found:
        print(f"  QB [{roster.qb.player_name[:20]}]  EPA/pass {roster.qb.epa_per_pass:+.3f}  Comp {roster.qb.comp_pct:.1%}  TD:INT {roster.qb.td_int_ratio:.1f}  {roster.qb.label()}")
    else:
        print(f"  QB Rating             {roster.qb.label()}  (limited data)")
    if roster.recruiting.rank_2025:
        print(f"  Recruiting [#{roster.recruiting.rank_2025} class]  {roster.recruiting.weighted_score:.0f} pts  {roster.recruiting.label()}")
    else:
        print(f"  Recruiting            {roster.recruiting.weighted_score:.0f} pts  {roster.recruiting.label()}")
    print(f"  Combined OFF adj: {roster.total_off_adjustment():.3f}  DEF adj: {roster.total_def_adjustment():.3f}")


def print_confidence(pred) -> None:
    """Print confidence score block."""
    if not pred.confidence:
        return
    c = pred.confidence
    W = 66
    print(f"\n  MODEL CONFIDENCE")
    print("─" * W)
    print(f"  {c.label()}")
    print(f"  Win prob strength: {c.prediction_strength:.0f}/40   Variance: {c.sim_consistency:.0f}/20   Signal agree: {c.signal_agreement:.0f}/25   Gap penalty: -{c.market_gap_penalty:.0f}/15")
    if c.classification == "HIGH":
        print(f"  → Signals aligned. Higher trust in this prediction.")
    elif c.classification == "MEDIUM":
        print(f"  → Some uncertainty. Moderate position sizing recommended.")
    else:
        print(f"  → Signals conflict or large market gap. Avoid strong positions.")
