"""
roster_factors.py
==================
Roster-based upgrades to the prediction model.
"""

import math
from dataclasses import dataclass, field
from typing import Optional

try:
    CFBD_OK = True
except ImportError:
    CFBD_OK = False


@dataclass
class ReturningProduction:
    pct_ppa_off:   float = 0.58
    pct_passing:   float = 0.55
    pct_receiving: float = 0.55
    pct_rushing:   float = 0.60
    usage_off:     float = 0.60
    rp_rating:     float = 1.0
    rp_impact:     float = 0.0

    def label(self) -> str:
        if self.rp_impact >= 0.06:  return "★★★ HIGH RETURN"
        if self.rp_impact >= 0.02:  return "★★  ABOVE AVG"
        if self.rp_impact >= -0.02: return "─   AVERAGE"
        if self.rp_impact >= -0.06: return "✗   BELOW AVG"
        return "✗✗  LOW RETURN"


@dataclass
class TransferPortalImpact:
    incoming_count:  int   = 0
    outgoing_count:  int   = 0
    incoming_score:  float = 0.0
    outgoing_score:  float = 0.0
    net_score:       float = 0.0
    off_adj:         float = 0.0
    def_adj:         float = 0.0
    qb_transfer_in:  bool  = False
    qb_transfer_out: bool  = False

    def label(self) -> str:
        if self.net_score >= 10:  return "★★★ MAJOR PORTAL GAIN"
        if self.net_score >= 4:   return "★★  PORTAL GAIN"
        if self.net_score >= 1:   return "★   SLIGHT GAIN"
        if self.net_score >= -1:  return "─   NEUTRAL"
        if self.net_score >= -4:  return "✗   PORTAL LOSS"
        return "✗✗  MAJOR PORTAL LOSS"


@dataclass
class QBRating:
    player_name:   str   = "Unknown"
    epa_per_pass:  float = 0.10
    comp_pct:      float = 0.62
    td_int_ratio:  float = 2.5
    yards_per_att: float = 7.5
    rushing_epa:   float = 0.0
    qb_impact:     float = 1.0
    data_found:    bool  = False

    def label(self) -> str:
        if self.qb_impact >= 1.30: return "★★★ ELITE QB"
        if self.qb_impact >= 1.15: return "★★  ABOVE AVERAGE QB"
        if self.qb_impact >= 0.90: return "─   AVERAGE QB"
        if self.qb_impact >= 0.75: return "✗   BELOW AVERAGE QB"
        return "✗✗  POOR QB SITUATION"


@dataclass
class RecruitingComposite:
    rank_2025:      Optional[int] = None
    rank_2024:      Optional[int] = None
    rank_2023:      Optional[int] = None
    rank_2022:      Optional[int] = None
    points_2025:    float = 0.0
    points_2024:    float = 0.0
    points_2023:    float = 0.0
    points_2022:    float = 0.0
    weighted_score: float = 0.0
    talent_score:   float = 1.0
    talent_impact:  float = 0.0

    def label(self) -> str:
        if self.talent_score >= 1.35: return "★★★ ELITE TALENT"
        if self.talent_score >= 1.15: return "★★  ABOVE AVERAGE"
        if self.talent_score >= 0.90: return "─   AVERAGE TALENT"
        if self.talent_score >= 0.70: return "✗   BELOW AVERAGE"
        return "✗✗  LOW TALENT BASE"


@dataclass
class ConfidenceScore:
    """
    Post-simulation trust filter.
    75-100 = HIGH CONFIDENCE
    55-74  = MEDIUM CONFIDENCE
    35-54  = LOW CONFIDENCE
    0-34   = HIGH VARIANCE
    """
    raw_score:           float = 70.0
    sim_consistency:     float = 0.0
    signal_agreement:    float = 0.0
    prediction_strength: float = 0.0
    market_gap_penalty:  float = 0.0
    classification:      str   = "MEDIUM"

    def label(self) -> str:
        if self.raw_score >= 75:
            return f"✅ HIGH CONFIDENCE ({self.raw_score:.0f}/100)"
        if self.raw_score >= 55:
            return f"⚠️  MEDIUM CONFIDENCE ({self.raw_score:.0f}/100)"
        if self.raw_score >= 35:
            return f"🟡 LOW CONFIDENCE ({self.raw_score:.0f}/100)"
        return f"📊 MODEL vs MARKET GAP ({self.raw_score:.0f}/100) — Verify before betting"


# ─────────────────────────────────────────────────────────────
# POSITION WEIGHTS
# ─────────────────────────────────────────────────────────────

TRANSFER_WEIGHTS = {
    "QB": 5.0, "OT": 3.5, "OG": 3.0, "OL": 3.2, "C": 3.0,
    "EDGE": 3.5, "DE": 3.2, "CB": 3.0, "S": 2.5, "DB": 2.5,
    "WR": 2.5, "TE": 2.0, "RB": 2.0,
    "LB": 2.5, "MLB": 2.5, "ILB": 2.5, "OLB": 2.8,
    "DT": 2.5, "DL": 2.5, "NT": 2.0,
    "K": 0.8, "P": 0.8, "LS": 0.5,
}

OFFENSE_POSITIONS = {"QB", "OT", "OG", "OL", "C", "WR", "TE", "RB"}
DEFENSE_POSITIONS = {"EDGE", "DE", "DT", "DL", "NT", "CB", "S", "DB", "LB", "MLB", "ILB", "OLB"}


def _transfer_weight(position: str) -> float:
    if not position:
        return 1.5
    return TRANSFER_WEIGHTS.get(position.upper().strip(), 1.5)


def _transfer_talent(rating, stars) -> float:
    if rating and rating > 0:
        return max(1.0, (rating - 0.79) / (1.0 - 0.79) * 4.0 + 1.0)
    if stars and stars > 0:
        return float(stars)
    return 2.0


# ─────────────────────────────────────────────────────────────
# CACHES + CONSTANTS
# ─────────────────────────────────────────────────────────────

_rp_cache  = {}
_tp_cache  = {}
_qb_cache  = {}
_rec_cache = {}

CFB_AVG_RETURN_PCT     = 0.58
CFB_AVG_EPA_PASS       = 0.10
CFB_AVG_COMP_PCT       = 0.62
CFB_AVG_TD_INT         = 2.5
CFB_AVG_YPA            = 7.5
CFB_AVG_RECRUITING_PTS = 190.0


# ─────────────────────────────────────────────────────────────
# STUB LOADERS (cfbd disabled due to pydantic conflict)
# ─────────────────────────────────────────────────────────────

def load_returning_production(client, year: int) -> dict:
    if year in _rp_cache:
        return _rp_cache[year]
    _rp_cache[year] = {}
    return {}

def get_returning_production(client, team: str, year: int) -> ReturningProduction:
    return load_returning_production(client, year).get(team, ReturningProduction())

def load_transfer_portal(client, year: int) -> dict:
    if year in _tp_cache:
        return _tp_cache[year]
    _tp_cache[year] = {}
    return {}

def get_transfer_portal_impact(client, team: str, year: int) -> TransferPortalImpact:
    return load_transfer_portal(client, year).get(team, TransferPortalImpact())

def load_qb_ratings(client, year: int) -> dict:
    if year in _qb_cache:
        return _qb_cache[year]
    _qb_cache[year] = {}
    return {}

def get_qb_rating(client, team: str, year: int) -> QBRating:
    return load_qb_ratings(client, year).get(team, QBRating())

def load_recruiting_rankings(client, year: int) -> dict:
    cache_key = f"recruiting_{year}"
    if cache_key in _rec_cache:
        return _rec_cache[cache_key]
    _rec_cache[cache_key] = {}
    return {}

def build_recruiting_composite(client, team: str, base_year: int) -> RecruitingComposite:
    return RecruitingComposite(talent_score=1.0, talent_impact=0.0)


# ─────────────────────────────────────────────────────────────
# CONFIDENCE SCORE
# ─────────────────────────────────────────────────────────────

def calc_confidence_score(
    simulated_margins,
    win_prob_a:  float,
    off_rating_a: float,
    def_rating_a: float,
    off_rating_b: float,
    def_rating_b: float,
    elo_a:        float,
    elo_b:        float,
    edge_a:       float,
) -> ConfidenceScore:
    import numpy as np

    # 1. Win probability strength (0-40 pts)
    stronger_prob = max(win_prob_a, 100 - win_prob_a)
    if stronger_prob >= 80:
        strength_score = 40.0
    elif stronger_prob >= 70:
        strength_score = 30.0
    elif stronger_prob >= 65:
        strength_score = 22.0
    elif stronger_prob >= 60:
        strength_score = 14.0
    elif stronger_prob >= 55:
        strength_score = 8.0
    else:
        strength_score = 3.0

    # 2. Simulation variance (0-25 pts)
    margin_std = float(np.std(simulated_margins))
    if margin_std < 10:
        std_score = 25.0
    elif margin_std < 13:
        std_score = 20.0
    elif margin_std < 16:
        std_score = 15.0
    elif margin_std < 20:
        std_score = 10.0
    elif margin_std < 25:
        std_score = 6.0
    else:
        std_score = 2.0

    # 3. Signal agreement (0-25 pts)
    pts_says_a  = (off_rating_a / max(def_rating_b, 0.1)) > (off_rating_b / max(def_rating_a, 0.1))
    elo_says_a  = elo_a > elo_b
    prob_says_a = win_prob_a > 50
    agreements  = sum([
        pts_says_a  == prob_says_a,
        elo_says_a  == prob_says_a,
        pts_says_a  == elo_says_a,
    ])
    signal_score = (agreements / 3) * 25

    # 4. Edge size bonus (0-15 pts) — bigger edge = more value
    gap = abs(edge_a)
    if gap >= 20:
        edge_bonus = 15.0
    elif gap >= 15:
        edge_bonus = 12.0
    elif gap >= 10:
        edge_bonus = 8.0
    elif gap >= 5:
        edge_bonus = 5.0
    elif gap >= 3:
        edge_bonus = 2.0
    else:
        edge_bonus = 0.0

    raw = strength_score + std_score + signal_score + edge_bonus
    raw = max(0, min(100, raw))

    if raw >= 75:
        cls = "HIGH"
    elif raw >= 55:
        cls = "MEDIUM"
    elif raw >= 35:
        cls = "LOW"
    else:
        cls = "HIGH VARIANCE"

    return ConfidenceScore(
        raw_score            = round(raw, 1),
        sim_consistency      = round(std_score, 1),
        signal_agreement     = round(signal_score, 1),
        prediction_strength  = round(strength_score, 1),
        market_gap_penalty   = round(edge_bonus, 1),
        classification       = cls,
    )


# ─────────────────────────────────────────────────────────────
# ROSTER SUMMARY
# ─────────────────────────────────────────────────────────────

@dataclass
class RosterFactors:
    returning:  ReturningProduction  = field(default_factory=ReturningProduction)
    portal:     TransferPortalImpact = field(default_factory=TransferPortalImpact)
    qb:         QBRating             = field(default_factory=QBRating)
    recruiting: RecruitingComposite  = field(default_factory=RecruitingComposite)

    def total_off_adjustment(self) -> float:
        adj = 1.0
        adj += self.returning.rp_impact
        adj += self.portal.off_adj
        adj += self.recruiting.talent_impact * 0.25
        return max(0.70, min(1.40, adj))

    def total_def_adjustment(self) -> float:
        adj = 1.0
        adj += self.returning.rp_impact * 0.70
        adj += self.portal.def_adj
        adj += self.recruiting.talent_impact * 0.25
        return max(0.70, min(1.40, adj))

    def qb_blend_offensive_rating(self, base_off_rating: float) -> float:
        QB_WEIGHT = 0.35
        return base_off_rating * (1 - QB_WEIGHT) + self.qb.qb_impact * QB_WEIGHT


def build_roster_factors(client, team: str, year: int) -> RosterFactors:
    return RosterFactors(
        returning  = get_returning_production(client, team, year),
        portal     = get_transfer_portal_impact(client, team, year),
        qb         = get_qb_rating(client, team, year),
        recruiting = build_recruiting_composite(client, team, year),
    )
