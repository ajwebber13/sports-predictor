"""
enhanced_predictor.py
======================
Enhanced prediction engine using all available signals:

  1. Base scoring (pts/game, YPP)
  2. Advanced metrics (EPA, success rate, pace, havoc)
  3. Multi-year historical weighting (3 seasons)
  4. Situational adjustments (weather, rest, travel)
  5. Market signals (line movement)
  6. ATS historical trends (as context, not prediction input)

The rating formula blends all signals with configurable weights.
Monte Carlo simulation (10,000+ runs) still drives probabilities.

Backward compatible: falls back to original predictor if
enhanced data is unavailable.
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple

from enhanced_data import EnhancedProfile, GameContext, ATSRecord
from situational import apply_context_adjustments, line_movement_signal, summarize_context
from predictor import NFL_CONSTANTS, CFB_CONSTANTS
from roster_factors import RosterFactors, ConfidenceScore, calc_confidence_score


# ─────────────────────────────────────────────────────────────
# SIGNAL WEIGHTS
# Controls how much each data source influences the final rating.
# Must sum to 1.0 within each category.
# ─────────────────────────────────────────────────────────────

OFFENSE_WEIGHTS = {
    "pts_current":    0.25,   # current season pts/game
    "pts_history":    0.15,   # multi-year weighted pts
    "epa":            0.20,   # EPA per play
    "success_rate":   0.15,   # success rate
    "ypp":            0.15,   # yards per play
    "turnovers":      0.05,   # TO rate (inverted)
    "pace":           0.05,   # plays per game (more plays = more scoring chances)
}

DEFENSE_WEIGHTS = {
    "pts_current":    0.25,
    "pts_history":    0.15,
    "epa_allowed":    0.25,   # EPA allowed per play
    "success_def":    0.15,   # opponent success rate
    "ypp_def":        0.15,   # yards allowed per play
    "havoc":          0.05,   # disruption rate
}

# League average EPA values (approximate FBS averages)
CFB_AVG_EPA_OFF   =  0.02    # slightly above zero for average FBS offense
CFB_AVG_EPA_DEF   = -0.02    # slightly negative for average FBS defense
CFB_AVG_SUCCESS   =  0.42    # 42% success rate average
CFB_AVG_PACE      = 72.0     # plays per game
CFB_AVG_HAVOC     =  0.18    # 18% disruption rate

NFL_AVG_EPA_OFF   =  0.03
NFL_AVG_EPA_DEF   = -0.03
NFL_AVG_SUCCESS   =  0.44
NFL_AVG_PACE      = 65.0
NFL_AVG_HAVOC     =  0.15


# ─────────────────────────────────────────────────────────────
# ENHANCED RATING ENGINE
# ─────────────────────────────────────────────────────────────

class EnhancedRatingEngine:
    """
    Converts EnhancedProfile into offensive/defensive strength ratings.
    Rating 1.0 = exactly league average.
    """

    def __init__(self, league: str):
        self.c = CFB_CONSTANTS if league == "CFB" else NFL_CONSTANTS
        self.league = league
        self.sos_weight = 0.20 if league == "CFB" else 0.10
        self.avg_epa_off = CFB_AVG_EPA_OFF if league == "CFB" else NFL_AVG_EPA_OFF
        self.avg_epa_def = CFB_AVG_EPA_DEF if league == "CFB" else NFL_AVG_EPA_DEF
        self.avg_success = CFB_AVG_SUCCESS if league == "CFB" else NFL_AVG_SUCCESS
        self.avg_pace    = CFB_AVG_PACE    if league == "CFB" else NFL_AVG_PACE
        self.avg_havoc   = CFB_AVG_HAVOC   if league == "CFB" else NFL_AVG_HAVOC

    def offensive_rating(self, p: EnhancedProfile) -> float:
        c = self.c
        w = OFFENSE_WEIGHTS

        # 1. Current season pts
        pts_r = (p.pts_off / c["league_avg_pts"]) * w["pts_current"]

        # 2. Multi-year weighted pts
        hist_pts = p.history.weighted_pts_off if p.history.weighted_pts_off > 0 else p.pts_off
        hist_r   = (hist_pts / c["league_avg_pts"]) * w["pts_history"]

        # 3. EPA (positive EPA = above average offense)
        # Normalize: average is ~0.02, range roughly -0.3 to +0.3
        epa_norm = 1.0 + (p.advanced.epa_off - self.avg_epa_off) / 0.15
        epa_norm = max(0.3, min(2.0, epa_norm))
        epa_r    = epa_norm * w["epa"]

        # 4. Success rate
        success_norm = p.advanced.success_rate_off / self.avg_success
        success_norm = max(0.5, min(1.8, success_norm))
        success_r    = success_norm * w["success_rate"]

        # 5. Yards per play
        ypp_r = (p.ypp_off / c["league_avg_ypp"]) * w["ypp"]

        # 6. Turnover rate (fewer TOs = higher rating)
        to_r = (c["league_avg_to_given"] / max(p.to_given, 0.5)) * w["turnovers"]

        # 7. Pace (more plays = more opportunities; normalize around avg)
        pace_norm = p.advanced.pace / self.avg_pace
        pace_norm = max(0.7, min(1.4, pace_norm))
        pace_r    = pace_norm * w["pace"]

        raw = pts_r + hist_r + epa_r + success_r + ypp_r + to_r + pace_r

        # SOS adjustment
        sos_adj = 1.0 + (p.sos - 0.5) * self.sos_weight
        inj_adj = 1.0 + p.injury_adj * 0.08

        # Trend bonus (improving offense gets slight boost)
        trend_bonus = 1.0 + (p.history.trend_off / 100.0) * 0.02

        return round(raw * sos_adj * inj_adj * trend_bonus, 4)

    def defensive_rating(self, p: EnhancedProfile) -> float:
        """Higher = better defense (suppresses opponent scoring)."""
        c = self.c
        w = DEFENSE_WEIGHTS

        # 1. Current pts allowed (inverted)
        pts_r = (c["league_avg_pts"] / max(p.pts_def, 5.0)) * w["pts_current"]

        # 2. Multi-year weighted pts allowed (inverted)
        hist_def = p.history.weighted_pts_def if p.history.weighted_pts_def > 0 else p.pts_def
        hist_r   = (c["league_avg_pts"] / max(hist_def, 5.0)) * w["pts_history"]

        # 3. EPA allowed (negative EPA = better defense; invert for rating)
        # Average defense allows ~-0.02 EPA; elite is -0.15, bad is +0.10
        epa_norm = 1.0 + (self.avg_epa_def - p.advanced.epa_def) / 0.12
        epa_norm = max(0.3, min(2.2, epa_norm))
        epa_r    = epa_norm * w["epa_allowed"]

        # 4. Opponent success rate (lower = better defense)
        success_norm = self.avg_success / max(p.advanced.success_rate_def, 0.25)
        success_norm = max(0.5, min(1.8, success_norm))
        success_r    = success_norm * w["success_def"]

        # 5. Yards per play allowed (inverted)
        ypp_r = (c["league_avg_ypp"] / max(p.ypp_def, 3.0)) * w["ypp_def"]

        # 6. Havoc rate (more disruption = better defense)
        havoc_norm = p.advanced.havoc / self.avg_havoc
        havoc_norm = max(0.5, min(2.0, havoc_norm))
        havoc_r    = havoc_norm * w["havoc"]

        raw = pts_r + hist_r + epa_r + success_r + ypp_r + havoc_r

        sos_adj = 1.0 + (p.sos - 0.5) * self.sos_weight

        return round(raw * sos_adj, 4)

    def expected_score(
        self,
        offense: EnhancedProfile,
        defense: EnhancedProfile,
        is_home: bool,
        neutral_site: bool,
    ) -> float:
        """Expected pts for offense team vs defense team."""
        off_r = self.offensive_rating(offense)
        def_r = self.defensive_rating(defense)

        base = self.c["league_avg_pts"] * off_r * (1.0 / def_r)

        if not neutral_site:
            adj = self.c["home_adv_pts"] * 0.5
            base += adj if is_home else -adj

        return max(base, 3.0)


# ─────────────────────────────────────────────────────────────
# ENHANCED PREDICTION OUTPUT
# ─────────────────────────────────────────────────────────────

@dataclass
class EnhancedPrediction:
    """Full enhanced prediction output."""
    team_a_name:         str
    team_b_name:         str

    # Win probabilities
    team_a_win_prob:     float
    team_b_win_prob:     float

    # Projected scores
    projected_pts_a:     float
    projected_pts_b:     float
    projected_total:     float
    score_range_a:       Tuple[float, float]
    score_range_b:       Tuple[float, float]

    # Spread
    spread_line:         float
    team_a_cover_prob:   float
    team_b_cover_prob:   float

    # Totals
    over_under_line:     float
    over_prob:           float
    under_prob:          float

    # Enhanced ratings
    off_rating_a:        float
    def_rating_a:        float
    off_rating_b:        float
    def_rating_b:        float

    # Advanced metrics display
    epa_off_a:           float
    epa_def_a:           float
    epa_off_b:           float
    epa_def_b:           float
    success_off_a:       float
    success_def_a:       float
    success_off_b:       float
    success_def_b:       float
    elo_a:               float
    elo_b:               float

    # ATS records
    ats_a:               ATSRecord
    ats_b:               ATSRecord

    # Situational
    context:             GameContext
    weather_adj:         float
    rest_adj_a:          float
    rest_adj_b:          float
    travel_adj_b:        float

    # Market edge
    sportsbook_implied_a: float
    sportsbook_implied_b: float
    model_prob_a:         float
    model_prob_b:         float
    edge_a:               float
    edge_b:               float

    simulations_run:     int
    roster_a:            RosterFactors = None
    roster_b:            RosterFactors = None
    confidence:          ConfidenceScore = None

    def edge_label(self, edge: float) -> str:
        if edge >= 10:   return "★★★ STRONG EDGE"
        if edge >= 6:    return "★★  MODERATE EDGE"
        if edge >= 3:    return "★   SLIGHT EDGE"
        if edge <= -10:  return "✗✗✗ STRONG FADE"
        if edge <= -6:   return "✗✗  MODERATE FADE"
        if edge <= -3:   return "✗   SLIGHT FADE"
        return "─   NEUTRAL"

    def to_dict(self) -> dict:
        return {
            "game": f"{self.team_a_name} vs {self.team_b_name}",
            "win_prob": {self.team_a_name: self.team_a_win_prob, self.team_b_name: self.team_b_win_prob},
            "projected_score": {self.team_a_name: self.projected_pts_a, self.team_b_name: self.projected_pts_b, "total": self.projected_total},
            "spread": {"line": self.spread_line, f"{self.team_a_name}_cover": self.team_a_cover_prob},
            "total": {"line": self.over_under_line, "over": self.over_prob, "under": self.under_prob},
            "ratings": {
                self.team_a_name: {"off": self.off_rating_a, "def": self.def_rating_a, "epa_off": self.epa_off_a, "epa_def": self.epa_def_a, "elo": self.elo_a},
                self.team_b_name: {"off": self.off_rating_b, "def": self.def_rating_b, "epa_off": self.epa_off_b, "epa_def": self.epa_def_b, "elo": self.elo_b},
            },
            "ats": {
                self.team_a_name: {"pct": self.ats_a.overall_pct, "record": f"{self.ats_a.overall_w}-{self.ats_a.overall_l}", "signal": self.ats_a.ats_signal()},
                self.team_b_name: {"pct": self.ats_b.overall_pct, "record": f"{self.ats_b.overall_w}-{self.ats_b.overall_l}", "signal": self.ats_b.ats_signal()},
            },
            "edge": {
                self.team_a_name: {"model": self.model_prob_a, "market": self.sportsbook_implied_a, "edge": self.edge_a},
                self.team_b_name: {"model": self.model_prob_b, "market": self.sportsbook_implied_b, "edge": self.edge_b},
            },
            "situational": {
                "weather": self.context.weather_summary(),
                "home_rest_days": self.context.home_rest_days,
                "away_rest_days": self.context.away_rest_days,
                "line_movement": self.context.line_movement,
                "market_signal": self.context.market_signal(),
            },
            "simulations": self.simulations_run,
            "confidence": {
                "score": self.confidence.raw_score if self.confidence else None,
                "classification": self.confidence.classification if self.confidence else None,
                "label": self.confidence.label() if self.confidence else "N/A",
            },
        }


# ─────────────────────────────────────────────────────────────
# ENHANCED PREDICTION ENGINE
# ─────────────────────────────────────────────────────────────

class EnhancedPredictionEngine:
    """
    Full enhanced prediction pipeline.
    Uses EnhancedProfile (replaces TeamStats) + GameContext.
    """

    def predict(
        self,
        profile_a:      EnhancedProfile,
        profile_b:      EnhancedProfile,
        spread_line:    float,
        over_under:     float,
        odds_a:         int,
        odds_b:         int,
        neutral_site:   bool  = False,
        a_is_home:      bool  = True,
        context:        Optional[GameContext] = None,
        simulations:    int   = 10000,
        roster_a:       Optional[RosterFactors] = None,
        roster_b:       Optional[RosterFactors] = None,
    ) -> EnhancedPrediction:

        league  = profile_a.league
        engine  = EnhancedRatingEngine(league)
        c       = CFB_CONSTANTS if league == "CFB" else NFL_CONSTANTS

        if context is None:
            context = GameContext()

        # ── Ratings ───────────────────────────────────────────
        off_a = engine.offensive_rating(profile_a)
        def_a = engine.defensive_rating(profile_a)
        off_b = engine.offensive_rating(profile_b)
        def_b = engine.defensive_rating(profile_b)

        # ── Expected scores (pre-context) ─────────────────────
        raw_a = engine.expected_score(profile_a, profile_b, is_home=a_is_home,    neutral_site=neutral_site)
        raw_b = engine.expected_score(profile_b, profile_a, is_home=not a_is_home, neutral_site=neutral_site)

        # ── Apply situational adjustments ─────────────────────
        exp_a, exp_b = apply_context_adjustments(raw_a, raw_b, context)

        # ── Market signal (slight probability nudge) ──────────
        market_adj_a, market_adj_b = line_movement_signal(context)
        # Convert to pts adjustment (1 pt edge ≈ 3% probability at midfield)
        exp_a += market_adj_a * 0.3
        exp_b += market_adj_b * 0.3

        # ── Monte Carlo ───────────────────────────────────────
        std = c["score_std_dev"]
        scores_a = np.maximum(np.random.normal(exp_a, std, simulations), 0)
        scores_b = np.maximum(np.random.normal(exp_b, std, simulations), 0)

        margin    = scores_a - scores_b
        n         = simulations

        win_a     = np.sum(scores_a > scores_b) / n * 100
        win_b     = np.sum(scores_b > scores_a) / n * 100
        cover_a   = np.sum(margin > spread_line)  / n * 100
        cover_b   = np.sum(margin < spread_line)  / n * 100
        over_p    = np.sum((scores_a + scores_b) > over_under) / n * 100
        under_p   = np.sum((scores_a + scores_b) < over_under) / n * 100

        r_a = (np.percentile(scores_a, 10), np.percentile(scores_a, 90))
        r_b = (np.percentile(scores_b, 10), np.percentile(scores_b, 90))

        # ── Market edge ───────────────────────────────────────
        from predictor import american_to_implied, remove_vig
        raw_mkt_a = american_to_implied(odds_a)
        raw_mkt_b = american_to_implied(odds_b)
        mkt_a, mkt_b = remove_vig(raw_mkt_a, raw_mkt_b)

        edge_a = win_a - mkt_a
        edge_b = win_b - mkt_b

        # ── Context adjustments for display ───────────────────
        from situational import weather_scoring_adjustment, rest_adjustment, travel_adjustment
        weather_adj = weather_scoring_adjustment(context)
        rest_adj_a  = rest_adjustment(context.home_rest_days) if a_is_home else rest_adjustment(context.away_rest_days)
        rest_adj_b  = rest_adjustment(context.away_rest_days) if a_is_home else rest_adjustment(context.home_rest_days)
        travel_adj_b = travel_adjustment(context.away_travel_miles if a_is_home else context.home_travel_miles)

        # ── Confidence score (post-simulation) ──────────────
        confidence = calc_confidence_score(
            simulated_margins   = margin,
            win_prob_a          = win_a,
            off_rating_a        = off_a,
            def_rating_a        = def_a,
            off_rating_b        = off_b,
            def_rating_b        = def_b,
            elo_a               = profile_a.advanced.elo,
            elo_b               = profile_b.advanced.elo,
            edge_a              = edge_a,
        )

        return EnhancedPrediction(
            team_a_name          = profile_a.team_name,
            team_b_name          = profile_b.team_name,
            team_a_win_prob      = round(win_a,   1),
            team_b_win_prob      = round(win_b,   1),
            projected_pts_a      = round(float(np.mean(scores_a)), 1),
            projected_pts_b      = round(float(np.mean(scores_b)), 1),
            projected_total      = round(float(np.mean(scores_a + scores_b)), 1),
            score_range_a        = (round(r_a[0], 1), round(r_a[1], 1)),
            score_range_b        = (round(r_b[0], 1), round(r_b[1], 1)),
            spread_line          = spread_line,
            team_a_cover_prob    = round(cover_a, 1),
            team_b_cover_prob    = round(cover_b, 1),
            over_under_line      = over_under,
            over_prob            = round(over_p,  1),
            under_prob           = round(under_p, 1),
            off_rating_a         = round(off_a, 3),
            def_rating_a         = round(def_a, 3),
            off_rating_b         = round(off_b, 3),
            def_rating_b         = round(def_b, 3),
            epa_off_a            = profile_a.advanced.epa_off,
            epa_def_a            = profile_a.advanced.epa_def,
            epa_off_b            = profile_b.advanced.epa_off,
            epa_def_b            = profile_b.advanced.epa_def,
            success_off_a        = profile_a.advanced.success_rate_off,
            success_def_a        = profile_a.advanced.success_rate_def,
            success_off_b        = profile_b.advanced.success_rate_off,
            success_def_b        = profile_b.advanced.success_rate_def,
            elo_a                = profile_a.advanced.elo,
            elo_b                = profile_b.advanced.elo,
            ats_a                = profile_a.ats,
            ats_b                = profile_b.ats,
            context              = context,
            weather_adj          = weather_adj,
            rest_adj_a           = rest_adj_a,
            rest_adj_b           = rest_adj_b,
            travel_adj_b         = travel_adj_b,
            sportsbook_implied_a = round(mkt_a, 1),
            sportsbook_implied_b = round(mkt_b, 1),
            model_prob_a         = round(win_a, 1),
            model_prob_b         = round(win_b, 1),
            edge_a               = round(edge_a, 1),
            edge_b               = round(edge_b, 1),
            simulations_run      = simulations,
            roster_a             = roster_a,
            roster_b             = roster_b,
            confidence           = confidence,
        )
