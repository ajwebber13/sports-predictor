"""
roster_factors.py
==================
The 5 core roster-based upgrades to the prediction model.

1. ReturningProduction  — how much experienced production returns
2. TransferPortalImpact — net gain/loss from portal moves
3. QBRating            — QB-anchored offensive anchor (35% min influence)
4. RecruitingComposite — 4-year talent floor (prevents overrating hot stat teams)
5. ConfidenceScore     — post-simulation trust filter

All values normalize to 1.0 = league average so they blend cleanly
into the existing rating engine.

Data sources: cfbd PlayersApi, RecruitingApi, StatsApi, MetricsApi
"""

import math
from dataclasses import dataclass, field
from typing import Optional, Dict, List

try:
    # import cfbd  # disabled - pydantic conflict
    CFBD_OK = True
except ImportError:
    CFBD_OK = False


# ─────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────

@dataclass
class ReturningProduction:
    """
    How much of last year's production returns this season.
    percentPPA = fraction of last year's EPA returning (0.0–1.0).

    High returning production → team is experienced, predictable, safer.
    Low returning production → heavy turnover, higher variance.

    rp_rating: 1.0 = average returning production (~55-60%)
    impact: ±10% max modifier on team ratings
    """
    pct_ppa_off:     float = 0.58   # typical FBS average
    pct_passing:     float = 0.55
    pct_receiving:   float = 0.55
    pct_rushing:     float = 0.60
    usage_off:       float = 0.60
    rp_rating:       float = 1.0    # normalized (1.0 = avg)
    rp_impact:       float = 0.0    # actual multiplier applied to rating

    def label(self) -> str:
        if self.rp_impact >= 0.06:  return "★★★ HIGH RETURN"
        if self.rp_impact >= 0.02:  return "★★  ABOVE AVG"
        if self.rp_impact >= -0.02: return "─   AVERAGE"
        if self.rp_impact >= -0.06: return "✗   BELOW AVG"
        return                              "✗✗  LOW RETURN"


@dataclass
class TransferPortalImpact:
    """
    Net roster change from the transfer portal.
    Weights QB and OL/EDGE/CB moves most heavily.

    net_impact: positive = team improved via portal, negative = lost more than gained
    off_adj: offensive efficiency adjustment (positive = gained offensive talent)
    def_adj: defensive efficiency adjustment
    """
    incoming_count: int   = 0
    outgoing_count: int   = 0
    incoming_score: float = 0.0   # weighted talent score of additions
    outgoing_score: float = 0.0   # weighted talent score of losses
    net_score:      float = 0.0   # incoming - outgoing
    off_adj:        float = 0.0   # ± offensive rating modifier
    def_adj:        float = 0.0   # ± defensive rating modifier
    qb_transfer_in: bool  = False
    qb_transfer_out: bool = False

    def label(self) -> str:
        if self.net_score >= 10:  return "★★★ MAJOR PORTAL GAIN"
        if self.net_score >= 4:   return "★★  PORTAL GAIN"
        if self.net_score >= 1:   return "★   SLIGHT GAIN"
        if self.net_score >= -1:  return "─   NEUTRAL"
        if self.net_score >= -4:  return "✗   PORTAL LOSS"
        return                            "✗✗  MAJOR PORTAL LOSS"


@dataclass
class QBRating:
    """
    QB-anchored offensive impact.
    Blended into offensive rating at a minimum 35% weight.

    qb_impact: 1.0 = league-average QB
    Components: EPA per dropback, completion%, TD:INT, yards per attempt
    """
    player_name:    str   = "Unknown"
    epa_per_pass:   float = 0.10     # avg ~0.10 for FBS starter
    comp_pct:       float = 0.62     # avg ~62%
    td_int_ratio:   float = 2.5      # avg ~2.5:1
    yards_per_att:  float = 7.5      # avg ~7.5 ypa
    rushing_epa:    float = 0.0      # QB rushing contribution
    qb_impact:      float = 1.0      # normalized rating
    data_found:     bool  = False

    def label(self) -> str:
        if self.qb_impact >= 1.30:  return "★★★ ELITE QB"
        if self.qb_impact >= 1.15:  return "★★  ABOVE AVERAGE QB"
        if self.qb_impact >= 0.90:  return "─   AVERAGE QB"
        if self.qb_impact >= 0.75:  return "✗   BELOW AVERAGE QB"
        return                              "✗✗  POOR QB SITUATION"


@dataclass
class RecruitingComposite:
    """
    4-year talent floor built from cfbd recruiting rankings.
    Weights: 40% most recent, 30%, 20%, 10%.

    Prevents stat-only teams from being over-rated (a team that overperformed
    their talent level likely regresses).
    Prevents top-talent teams from being under-rated early in a season.

    talent_score: 1.0 = P5 average talent
    """
    rank_2025:      Optional[int]   = None
    rank_2024:      Optional[int]   = None
    rank_2023:      Optional[int]   = None
    rank_2022:      Optional[int]   = None
    points_2025:    float = 0.0
    points_2024:    float = 0.0
    points_2023:    float = 0.0
    points_2022:    float = 0.0
    weighted_score: float = 0.0
    talent_score:   float = 1.0     # normalized
    talent_impact:  float = 0.0     # ± contribution to base rating (max ±0.20)

    def label(self) -> str:
        if self.talent_score >= 1.35: return "★★★ ELITE TALENT"
        if self.talent_score >= 1.15: return "★★  ABOVE AVERAGE"
        if self.talent_score >= 0.90: return "─   AVERAGE TALENT"
        if self.talent_score >= 0.70: return "✗   BELOW AVERAGE"
        return                                "✗✗  LOW TALENT BASE"


@dataclass
class ConfidenceScore:
    """
    Post-simulation trust filter.
    Measures how much to trust this prediction for betting decisions.

    Components:
      sim_consistency  — low variance in simulated outcomes = higher confidence
      signal_agreement — do EPA, pts, and Elo all agree on the winner?
      prediction_strength — extreme win probs (85%+) are more reliable
      market_gap_penalty — large model vs market gaps suggest missing info

    Ranges:
      80–100 = HIGH CONFIDENCE (signals strongly aligned, low variance)
      60–79  = MEDIUM CONFIDENCE (some disagreement, use with caution)
      <60    = HIGH VARIANCE (avoid strong positions, model is uncertain)
    """
    raw_score:          float = 70.0
    sim_consistency:    float = 0.0
    signal_agreement:   float = 0.0
    prediction_strength: float = 0.0
    market_gap_penalty: float = 0.0
    classification:     str   = "MEDIUM"

    def label(self) -> str:
        if self.raw_score >= 80: return f"✅ HIGH CONFIDENCE ({self.raw_score:.0f}/100)"
        if self.raw_score >= 60: return f"⚠️  MEDIUM CONFIDENCE ({self.raw_score:.0f}/100)"
        return                          f"🔴 HIGH VARIANCE ({self.raw_score:.0f}/100) — Use Caution"


# ─────────────────────────────────────────────────────────────
# POSITION WEIGHTS FOR TRANSFER PORTAL
# ─────────────────────────────────────────────────────────────

TRANSFER_WEIGHTS = {
    "QB": 5.0,
    "OT": 3.5, "OG": 3.0, "OL": 3.2, "C": 3.0,
    "EDGE": 3.5, "DE": 3.2,
    "CB": 3.0, "S": 2.5, "DB": 2.5,
    "WR": 2.5, "TE": 2.0,
    "RB": 2.0,
    "LB": 2.5, "MLB": 2.5, "ILB": 2.5, "OLB": 2.8,
    "DT": 2.5, "DL": 2.5, "NT": 2.0,
    "K": 0.8, "P": 0.8, "LS": 0.5,
}

# Which positions impact offense vs defense
OFFENSE_POSITIONS = {"QB", "OT", "OG", "OL", "C", "WR", "TE", "RB"}
DEFENSE_POSITIONS = {"EDGE", "DE", "DT", "DL", "NT", "CB", "S", "DB", "LB", "MLB", "ILB", "OLB"}


def _transfer_weight(position: str) -> float:
    """Get position weight for transfer portal impact."""
    if not position:
        return 1.5
    pos = position.upper().strip()
    return TRANSFER_WEIGHTS.get(pos, 1.5)


def _transfer_talent(rating: Optional[float], stars: Optional[int]) -> float:
    """
    Convert player rating/stars to talent value.
    cfbd player rating: typically 0.8–1.0 scale (0.98+ = 5-star).
    """
    if rating and rating > 0:
        # Map 0.80-1.00 to 1.0-5.0 talent scale
        return max(1.0, (rating - 0.79) / (1.0 - 0.79) * 4.0 + 1.0)
    if stars and stars > 0:
        return float(stars)
    return 2.0   # default: 2-star talent


# ─────────────────────────────────────────────────────────────
# CACHES
# ─────────────────────────────────────────────────────────────

_rp_cache  = {}   # {year: {team: ReturningProduction}}
_tp_cache  = {}   # {year: {team: TransferPortalImpact}}
_qb_cache  = {}   # {year: {team: QBRating}}
_rec_cache = {}   # {year: {team: RecruitingComposite}}


# ─────────────────────────────────────────────────────────────
# 1. RETURNING PRODUCTION
# ─────────────────────────────────────────────────────────────

# Average FBS returning production ~57-60% of PPA
CFB_AVG_RETURN_PCT = 0.58


def load_returning_production(client, year: int) -> dict:
    """
    Load returning production for all teams.
    Returns {team_name: ReturningProduction}.
    """
    if year in _rp_cache:
        return _rp_cache[year]

    try:
        players_api = cfbd.PlayersApi(client._api_client)
        raw = players_api.get_returning_production(year=year)
        result = {}

        for r in raw:
            if not r.team:
                continue

            pct_off = float(r.percent_ppa or CFB_AVG_RETURN_PCT)

            # Normalize: 1.0 = average (CFB_AVG_RETURN_PCT)
            rp_norm = pct_off / CFB_AVG_RETURN_PCT
            rp_norm = max(0.4, min(1.8, rp_norm))

            # Impact: max ±10% on ratings, linear around average
            rp_impact = (rp_norm - 1.0) * 0.10
            rp_impact = max(-0.10, min(0.10, rp_impact))

            result[r.team] = ReturningProduction(
                pct_ppa_off  = round(pct_off, 4),
                pct_passing  = round(float(r.percent_passing_ppa or pct_off), 4),
                pct_receiving= round(float(r.percent_receiving_ppa or pct_off), 4),
                pct_rushing  = round(float(r.percent_rushing_ppa or pct_off), 4),
                usage_off    = round(float(r.usage or 0.60), 4),
                rp_rating    = round(rp_norm, 4),
                rp_impact    = round(rp_impact, 4),
            )

        _rp_cache[year] = result
        print(f"  ✓ Returning production {year}: {len(result)} teams")
        return result
    except Exception as e:
        print(f"  ⚠ Returning production {year} failed: {e}")
        _rp_cache[year] = {}
        return {}


def get_returning_production(client, team: str, year: int) -> ReturningProduction:
    all_rp = load_returning_production(client, year)
    return all_rp.get(team, ReturningProduction())


# ─────────────────────────────────────────────────────────────
# 2. TRANSFER PORTAL IMPACT
# ─────────────────────────────────────────────────────────────

def load_transfer_portal(client, year: int) -> dict:
    """
    Load transfer portal data for all teams.
    Returns {team_name: TransferPortalImpact}.
    """
    if year in _tp_cache:
        return _tp_cache[year]

    try:
        players_api = cfbd.PlayersApi(client._api_client)
        transfers = players_api.get_transfer_portal(year=year)

        # Build per-team impact
        team_data = {}   # {team: {incoming: [], outgoing: []}}

        for t in transfers:
            pos   = (t.position or "").upper().strip()
            dest  = t.destination or ""
            orig  = t.origin or ""
            rat   = getattr(t, "rating", None)
            stars = getattr(t, "stars", None)
            talent = _transfer_talent(rat, stars)
            weight = _transfer_weight(pos)
            score  = talent * weight

            # Incoming to destination
            if dest:
                if dest not in team_data:
                    team_data[dest] = {"in": [], "out": []}
                team_data[dest]["in"].append({
                    "pos": pos, "score": score, "talent": talent,
                    "is_qb": pos == "QB", "is_off": pos in OFFENSE_POSITIONS,
                })

            # Outgoing from origin
            if orig:
                if orig not in team_data:
                    team_data[orig] = {"in": [], "out": []}
                team_data[orig]["out"].append({
                    "pos": pos, "score": score, "talent": talent,
                    "is_qb": pos == "QB", "is_off": pos in OFFENSE_POSITIONS,
                })

        result = {}
        for team, data in team_data.items():
            in_score  = sum(p["score"] for p in data["in"])
            out_score = sum(p["score"] for p in data["out"])
            net       = in_score - out_score

            # Separate offensive and defensive impact
            in_off  = sum(p["score"] for p in data["in"]  if p["is_off"])
            out_off = sum(p["score"] for p in data["out"] if p["is_off"])
            in_def  = sum(p["score"] for p in data["in"]  if not p["is_off"])
            out_def = sum(p["score"] for p in data["out"] if not p["is_off"])

            # Scale net to ±0.08 max rating adjustment
            # Average FBS portal activity: ~10-15 pts net score
            off_adj = max(-0.08, min(0.08, (in_off - out_off) / 30.0 * 0.08))
            def_adj = max(-0.08, min(0.08, (in_def - out_def) / 30.0 * 0.08))

            result[team] = TransferPortalImpact(
                incoming_count = len(data["in"]),
                outgoing_count = len(data["out"]),
                incoming_score = round(in_score,  2),
                outgoing_score = round(out_score, 2),
                net_score      = round(net,       2),
                off_adj        = round(off_adj,   4),
                def_adj        = round(def_adj,   4),
                qb_transfer_in  = any(p["is_qb"] for p in data["in"]),
                qb_transfer_out = any(p["is_qb"] for p in data["out"]),
            )

        _tp_cache[year] = result
        print(f"  ✓ Transfer portal {year}: {len(result)} teams")
        return result
    except Exception as e:
        print(f"  ⚠ Transfer portal {year} failed: {e}")
        _tp_cache[year] = {}
        return {}


def get_transfer_portal_impact(client, team: str, year: int) -> TransferPortalImpact:
    all_tp = load_transfer_portal(client, year)
    return all_tp.get(team, TransferPortalImpact())


# ─────────────────────────────────────────────────────────────
# 3. QB RATING
# ─────────────────────────────────────────────────────────────

# FBS average QB benchmarks
CFB_AVG_EPA_PASS = 0.10     # average EPA per passing play
CFB_AVG_COMP_PCT = 0.62     # 62% completion
CFB_AVG_TD_INT   = 2.5      # 2.5:1 TD to INT ratio
CFB_AVG_YPA      = 7.5      # 7.5 yards per attempt


def load_qb_ratings(client, year: int) -> dict:
    """
    Build QB ratings for all teams.
    Uses cfbd player PPA (EPA) + passing stats.
    Returns {team_name: QBRating}.
    """
    if year in _qb_cache:
        return _qb_cache[year]

    result = {}

    try:
        metrics_api = cfbd.MetricsApi(client._api_client)

        # Get QB EPA per play (this is the primary quality signal)
        qb_ppa = metrics_api.get_predicted_points_added_by_player_season(
            year=year,
            position="QB",
            threshold=100,          # min 100 plays for meaningful sample
            exclude_garbage_time=True,
        )

        # Build {team: best_qb_ppa} — take the QB with most passing PPA
        team_qb_ppa = {}
        for q in qb_ppa:
            if not q.team:
                continue
            avg_pass = getattr(q.average_ppa, "pass", None) if q.average_ppa else None
            if avg_pass is None:
                continue
            avg_pass = float(avg_pass)
            if q.team not in team_qb_ppa or avg_pass > team_qb_ppa[q.team][1]:
                name = f"{getattr(q, 'name', 'Unknown')}"
                team_qb_ppa[q.team] = (name, avg_pass)

    except Exception as e:
        print(f"  ⚠ QB PPA {year} failed: {e}")
        team_qb_ppa = {}

    try:
        stats_api = cfbd.StatsApi(client._api_client)

        # Get passing stats for all QBs
        passing = stats_api.get_player_season_stats(
            year=year,
            season_type=cfbd.SeasonType.REGULAR,
            category="passing",
        )

        # Group by team, find starting QB (most attempts)
        team_passing = {}
        for p in passing:
            if not p.team or not p.stat:
                continue
            team = p.team
            if team not in team_passing:
                team_passing[team] = {}
            stat_type = p.stat_type or ""
            try:
                val = float(p.stat)
                if stat_type not in team_passing[team]:
                    team_passing[team][stat_type] = {}
                player = p.player or "Unknown"
                if player not in team_passing[team][stat_type]:
                    team_passing[team][stat_type][player] = 0.0
                team_passing[team][stat_type][player] += val
            except:
                pass

    except Exception as e:
        print(f"  ⚠ QB passing stats {year} failed: {e}")
        team_passing = {}

    # Combine PPA + passing stats into QB rating
    all_teams = set(list(team_qb_ppa.keys()) + list(team_passing.keys()))

    for team in all_teams:
        ppa_data  = team_qb_ppa.get(team)
        pass_data = team_passing.get(team, {})

        # EPA per pass (primary signal, weight 40%)
        epa_pass  = ppa_data[1] if ppa_data else CFB_AVG_EPA_PASS
        name      = ppa_data[0] if ppa_data else "Unknown"
        epa_norm  = 1.0 + (epa_pass - CFB_AVG_EPA_PASS) / 0.12

        # Completion % (weight 25%)
        comp_data  = pass_data.get("PCT", {})
        comp_pct   = (max(comp_data.values()) if comp_data else CFB_AVG_COMP_PCT) / 100.0
        comp_pct   = min(0.85, max(0.45, comp_pct))   # reasonable range
        comp_norm  = comp_pct / CFB_AVG_COMP_PCT

        # TD:INT ratio (weight 20%)
        td_data    = pass_data.get("TD", {})
        int_data   = pass_data.get("INT", {})
        total_tds  = sum(td_data.values()) if td_data else 0
        total_ints = sum(int_data.values()) if int_data else 1
        td_int     = total_tds / max(total_ints, 1)
        td_int_norm = td_int / CFB_AVG_TD_INT

        # Yards per attempt (weight 15%)
        ypa_data  = pass_data.get("YPA", {})
        ypa       = (max(ypa_data.values()) if ypa_data else CFB_AVG_YPA)
        ypa_norm  = ypa / CFB_AVG_YPA

        # Blend (weights must sum to 1.0)
        raw_impact = (
            epa_norm  * 0.40 +
            comp_norm * 0.25 +
            td_int_norm * 0.20 +
            ypa_norm  * 0.15
        )

        # Cap at reasonable range
        raw_impact = max(0.50, min(1.80, raw_impact))

        result[team] = QBRating(
            player_name   = name,
            epa_per_pass  = round(epa_pass, 4),
            comp_pct      = round(comp_pct, 4),
            td_int_ratio  = round(td_int,   2),
            yards_per_att = round(ypa,      2),
            qb_impact     = round(raw_impact, 4),
            data_found    = ppa_data is not None,
        )

    _qb_cache[year] = result
    print(f"  ✓ QB ratings {year}: {len(result)} teams")
    return result


def get_qb_rating(client, team: str, year: int) -> QBRating:
    all_qb = load_qb_ratings(client, year)
    return all_qb.get(team, QBRating())


# ─────────────────────────────────────────────────────────────
# 4. RECRUITING COMPOSITE
# ─────────────────────────────────────────────────────────────

# P5 average recruiting points (approximate cfbd scale)
CFB_AVG_RECRUITING_PTS = 190.0


def load_recruiting_rankings(client, year: int) -> dict:
    """Load team recruiting rankings for a year. Returns {team: TeamRecruitingRanking}."""
    cache_key = f"recruiting_{year}"
    if cache_key in _rec_cache:
        return _rec_cache[cache_key]
    try:
        rec_api = cfbd.RecruitingApi(client._api_client)
        raw = rec_api.get_team_recruiting_rankings(year=year)
        result = {r.team: r for r in raw if r.team}
        _rec_cache[cache_key] = result
        return result
    except Exception as e:
        print(f"  ⚠ Recruiting {year} failed: {e}")
        _rec_cache[cache_key] = {}
        return {}


def build_recruiting_composite(client, team: str, base_year: int) -> RecruitingComposite:
    """
    Build 4-year recruiting composite.
    Weights: 40% most recent, 30%, 20%, 10%.
    """
    years   = [base_year, base_year-1, base_year-2, base_year-3]
    weights = [0.40, 0.30, 0.20, 0.10]

    points = []
    ranks  = []

    for yr in years:
        data = load_recruiting_rankings(client, yr)
        entry = data.get(team)
        if entry and entry.points:
            points.append(float(entry.points))
            ranks.append(int(entry.rank) if entry.rank else None)
        else:
            points.append(None)
            ranks.append(None)

    # Weighted average of recruiting points
    weighted_pts = 0.0
    total_w      = 0.0
    for pts, w in zip(points, weights):
        if pts is not None and pts > 0:
            weighted_pts += pts * w
            total_w      += w

    if total_w == 0:
        # No data found — assume mid-major level talent
        return RecruitingComposite(talent_score=0.70, talent_impact=-0.06)

    avg_pts = weighted_pts / total_w

    # Normalize: 1.0 = P5 average recruiting
    # Log scale prevents top programs from dominating excessively
    # Typical range: Alabama ~350pts → 1.84, Sun Belt team ~80pts → 0.42
    talent_norm = math.log(max(avg_pts, 10)) / math.log(CFB_AVG_RECRUITING_PTS)
    talent_norm = max(0.40, min(1.90, talent_norm))

    # Impact: max ±20% on base rating
    talent_impact = (talent_norm - 1.0) * 0.20
    talent_impact = max(-0.20, min(0.20, talent_impact))

    return RecruitingComposite(
        rank_2025    = ranks[0],
        rank_2024    = ranks[1],
        rank_2023    = ranks[2],
        rank_2022    = ranks[3],
        points_2025  = points[0] or 0.0,
        points_2024  = points[1] or 0.0,
        points_2023  = points[2] or 0.0,
        points_2022  = points[3] or 0.0,
        weighted_score = round(avg_pts, 1),
        talent_score   = round(talent_norm, 4),
        talent_impact  = round(talent_impact, 4),
    )


# ─────────────────────────────────────────────────────────────
# 5. CONFIDENCE SCORE (post-simulation)
# ─────────────────────────────────────────────────────────────

def calc_confidence_score(
    simulated_margins:   "np.ndarray",
    win_prob_a:          float,
    off_rating_a:        float,
    def_rating_a:        float,
    off_rating_b:        float,
    def_rating_b:        float,
    elo_a:               float,
    elo_b:               float,
    edge_a:              float,
) -> ConfidenceScore:
    """
    Calculate model confidence after Monte Carlo simulation.

    High confidence = signals agree, low variance, strong prediction.
    Low confidence = signals disagree, high variance, large market gap.

    Scoring (100 pts total):
      Win probability strength  0–40 pts  (how far from 50/50)
      Simulation variance       0–20 pts  (low spread = more certain)
      Signal agreement          0–25 pts  (EPA, pts, Elo all agree)
      Market gap penalty        0–15 pts  (large gaps = missing info)
    """
    import numpy as np

    # 1. Win probability strength (0–40 pts)
    # The further from 50/50, the more reliable the prediction
    stronger_prob = max(win_prob_a, 100 - win_prob_a)
    if stronger_prob >= 90:
        strength_score = 40.0
    elif stronger_prob >= 80:
        strength_score = 32.0
    elif stronger_prob >= 70:
        strength_score = 22.0
    elif stronger_prob >= 60:
        strength_score = 12.0
    else:
        strength_score = 3.0   # near 50/50 — very uncertain

    # 2. Simulation variance (0–20 pts)
    # Low margin std = model has consistent outcome = more reliable
    margin_std = float(np.std(simulated_margins))
    if margin_std < 13:
        std_score = 20.0
    elif margin_std < 16:
        std_score = 16.0
    elif margin_std < 19:
        std_score = 11.0
    elif margin_std < 22:
        std_score = 6.0
    else:
        std_score = 2.0

    # 3. Signal agreement (0–25 pts)
    # Do pts-based rating, Elo, and win probability all agree on the winner?
    pts_says_a = (off_rating_a / max(def_rating_b, 0.1)) > (off_rating_b / max(def_rating_a, 0.1))
    elo_says_a = elo_a > elo_b
    prob_says_a = win_prob_a > 50

    agreements = sum([
        pts_says_a  == prob_says_a,
        elo_says_a  == prob_says_a,
        pts_says_a  == elo_says_a,
    ])
    signal_score = (agreements / 3) * 25

    # 4. Market gap penalty (0–15 pts deducted)
    # Large model vs market gap often means the model is missing something
    # (roster changes, coaching, news) — penalize trust accordingly
    gap = abs(edge_a)
    if gap >= 30:
        gap_penalty = 15.0
    elif gap >= 20:
        gap_penalty = 10.0
    elif gap >= 10:
        gap_penalty = 5.0
    else:
        gap_penalty = 0.0

    raw = strength_score + std_score + signal_score - gap_penalty
    raw = max(0, min(100, raw))

    cls = "HIGH" if raw >= 80 else ("MEDIUM" if raw >= 60 else "HIGH VARIANCE")

    return ConfidenceScore(
        raw_score           = round(raw, 1),
        sim_consistency     = round(std_score, 1),
        signal_agreement    = round(signal_score, 1),
        prediction_strength = round(strength_score, 1),
        market_gap_penalty  = round(gap_penalty, 1),
        classification      = cls,
    )


# ─────────────────────────────────────────────────────────────
# ROSTER SUMMARY (all 5 factors for one team)
# ─────────────────────────────────────────────────────────────

@dataclass
class RosterFactors:
    """All 5 roster factors bundled for one team."""
    returning:  ReturningProduction = field(default_factory=ReturningProduction)
    portal:     TransferPortalImpact = field(default_factory=TransferPortalImpact)
    qb:         QBRating = field(default_factory=QBRating)
    recruiting: RecruitingComposite = field(default_factory=RecruitingComposite)

    def total_off_adjustment(self) -> float:
        """Combined offensive rating multiplier from all roster factors."""
        adj = 1.0
        adj += self.returning.rp_impact         # ±10% from returning production
        adj += self.portal.off_adj              # ±8% from portal
        adj += self.recruiting.talent_impact * 0.25  # 25% of talent impact on offense
        return max(0.70, min(1.40, adj))

    def total_def_adjustment(self) -> float:
        """Combined defensive rating multiplier from all roster factors."""
        adj = 1.0
        adj += self.returning.rp_impact * 0.70  # defense returns matter slightly less
        adj += self.portal.def_adj
        adj += self.recruiting.talent_impact * 0.25
        return max(0.70, min(1.40, adj))

    def qb_blend_offensive_rating(self, base_off_rating: float) -> float:
        """
        Blend QB impact into offensive rating at 35% minimum weight.
        QB is the single most important offensive player.
        """
        QB_WEIGHT = 0.35
        non_qb    = base_off_rating * (1 - QB_WEIGHT)
        qb_part   = self.qb.qb_impact * QB_WEIGHT
        return non_qb + qb_part


def build_roster_factors(client, team: str, year: int) -> RosterFactors:
    """Build complete RosterFactors for a team."""
    return RosterFactors(
        returning  = get_returning_production(client, team, year),
        portal     = get_transfer_portal_impact(client, team, year),
        qb         = get_qb_rating(client, team, year),
        recruiting = build_recruiting_composite(client, team, year),
    )
