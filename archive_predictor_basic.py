"""
Sports Betting Prediction Engine
=================================
NFL & College Football | Monte Carlo Probability Engine
Version 1.0

Architecture:
  TeamStats       → raw stats input
  RatingEngine    → normalized off/def strength ratings
  MonteCarloSim   → 10,000+ game simulations
  PredictionEngine→ orchestrates rating + sim + edge calc
  GamePrediction  → structured output object
"""

import numpy as np
from dataclasses import dataclass
from typing import Tuple, Dict

# ─────────────────────────────────────────────────────────────
# LEAGUE CONSTANTS
# ─────────────────────────────────────────────────────────────

NFL_CONSTANTS = {
    "league_avg_pts":      22.5,   # league-wide scoring avg
    "league_avg_ypp":       5.5,   # yards per play avg
    "league_avg_to_given":  1.4,   # turnovers committed per game
    "league_avg_to_forced": 1.4,   # turnovers forced per game
    "score_std_dev":       10.5,   # std dev of team scores (game variance)
    "home_adv_pts":         2.5,   # raw home field value in points
}

CFB_CONSTANTS = {
    "league_avg_pts":      29.0,
    "league_avg_ypp":       6.0,
    "league_avg_to_given":  1.6,
    "league_avg_to_forced": 1.6,
    "score_std_dev":       14.0,   # CFB has higher variance
    "home_adv_pts":         3.5,
}


# ─────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────────────────────

@dataclass
class TeamStats:
    """
    Full statistical profile for one team.
    Use season averages, optionally weighted toward recent games.

    league: "NFL" or "CFB"
    sos   : strength of schedule (0.0=easiest to 1.0=hardest, 0.5=average)
            More impactful for CFB where schedule quality varies widely.
    injury_adj: manual override (-0.2 to +0.2)
                negative = key players out, positive = fully healthy
    """
    name:              str
    league:            str   # "NFL" or "CFB"

    # Offense
    pts_per_game_off:  float  # avg pts scored per game
    yards_per_play_off: float  # offensive yards per play

    # Defense
    pts_per_game_def:  float  # avg pts allowed per game
    yards_per_play_def: float  # defensive yards per play allowed

    # Turnovers
    turnovers_given:   float  # avg TOs committed per game
    turnovers_forced:  float  # avg TOs forced per game

    # Situational splits
    home_pts_avg:      float  # avg pts scored at home
    away_pts_avg:      float  # avg pts scored away

    # Recent form (last 3–5 games)
    recent_pts_scored:  float
    recent_pts_allowed: float

    # Modifiers
    sos:               float = 0.5
    injury_adj:        float = 0.0


@dataclass
class MatchupInput:
    """
    Configuration for a single game prediction.

    spread_line    : points team_a is favored by (positive = A favored)
                     e.g., 3.5 → A is -3.5, B is +3.5
    team_a_odds    : American moneyline for team_a (e.g., -185 or +140)
    team_b_odds    : American moneyline for team_b
    neutral_site   : True removes home field advantage entirely
    team_a_is_home : True if team_a is the home team
    simulations    : number of Monte Carlo iterations (10,000 minimum)
    """
    team_a:         TeamStats
    team_b:         TeamStats
    spread_line:    float
    over_under_line: float
    team_a_odds:    int
    team_b_odds:    int
    neutral_site:   bool  = False
    team_a_is_home: bool  = True
    simulations:    int   = 10000


@dataclass
class GamePrediction:
    """
    Full prediction output for a matchup.
    All probabilities expressed as percentages (0–100).
    Edge = model_prob − market_prob (positive = model sees value).
    """
    team_a_name:         str
    team_b_name:         str

    # Win probabilities
    team_a_win_prob:     float
    team_b_win_prob:     float

    # Projected scores
    projected_pts_a:     float
    projected_pts_b:     float
    projected_total:     float

    # Score ranges (10th–90th percentile)
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

    # Internal ratings (diagnostic)
    off_rating_a:        float
    def_rating_a:        float
    off_rating_b:        float
    def_rating_b:        float

    # Edge analysis
    sportsbook_implied_a: float
    sportsbook_implied_b: float
    model_prob_a:         float
    model_prob_b:         float
    edge_a:               float
    edge_b:               float

    simulations_run:     int

    def edge_label(self, edge: float) -> str:
        """Human-readable edge signal."""
        if edge >= 10:   return "★★★ STRONG EDGE"
        if edge >= 6:    return "★★  MODERATE EDGE"
        if edge >= 3:    return "★   SLIGHT EDGE"
        if edge <= -10:  return "✗✗✗ STRONG FADE"
        if edge <= -6:   return "✗✗  MODERATE FADE"
        if edge <= -3:   return "✗   SLIGHT FADE"
        return            "─   NEUTRAL"

    def to_dict(self) -> dict:
        """Serialize for API or storage use."""
        return {
            "game": f"{self.team_a_name} vs {self.team_b_name}",
            "win_prob": {self.team_a_name: self.team_a_win_prob,
                         self.team_b_name: self.team_b_win_prob},
            "projected_score": {self.team_a_name: self.projected_pts_a,
                                 self.team_b_name: self.projected_pts_b,
                                 "total": self.projected_total},
            "spread": {"line": self.spread_line,
                       f"{self.team_a_name}_cover": self.team_a_cover_prob,
                       f"{self.team_b_name}_cover": self.team_b_cover_prob},
            "total":  {"line": self.over_under_line,
                       "over": self.over_prob, "under": self.under_prob},
            "ratings": {self.team_a_name: {"off": self.off_rating_a, "def": self.def_rating_a},
                        self.team_b_name: {"off": self.off_rating_b, "def": self.def_rating_b}},
            "edge":    {self.team_a_name: {"model": self.model_prob_a,
                                            "market": self.sportsbook_implied_a,
                                            "edge": self.edge_a},
                        self.team_b_name: {"model": self.model_prob_b,
                                            "market": self.sportsbook_implied_b,
                                            "edge": self.edge_b}},
            "simulations": self.simulations_run,
        }


# ─────────────────────────────────────────────────────────────
# RATING ENGINE
# ─────────────────────────────────────────────────────────────

class RatingEngine:
    """
    Converts raw team stats into normalized strength ratings.

    Rating = 1.0  →  exactly league average
    Rating > 1.0  →  above average (offense: scores more / defense: allows less)
    Rating < 1.0  →  below average

    Weighting (offensive):
      40% — pts per game
      25% — yards per play
      25% — recent form (last 3–5 games)
      10% — turnover penalty
      ×SOS adjustment (bigger impact in CFB)

    Weighting (defensive):
      40% — pts allowed (inverted)
      25% — yards per play allowed (inverted)
      25% — recent pts allowed (inverted)
      10% — turnovers forced bonus
    """

    def __init__(self, league: str):
        self.c = NFL_CONSTANTS if league == "NFL" else CFB_CONSTANTS
        # CFB schedule quality matters more; amplify SOS effect
        self.sos_weight = 0.10 if league == "NFL" else 0.20

    def offensive_rating(self, t: TeamStats) -> float:
        """
        All components are normalized ratios (team / league_avg).
        Weights sum to 1.0 → average team returns exactly 1.0.

          pts_ratio    > 1 when scoring above avg (good offense)
          ypp_ratio    > 1 when gaining more yards/play (good offense)
          recent_ratio > 1 when hot recently
          to_ratio     > 1 when committing fewer TOs (inverted: league/team)
        """
        c = self.c
        pts_ratio    = t.pts_per_game_off   / c["league_avg_pts"]
        ypp_ratio    = t.yards_per_play_off / c["league_avg_ypp"]
        recent_ratio = t.recent_pts_scored  / c["league_avg_pts"]
        to_ratio     = c["league_avg_to_given"] / max(t.turnovers_given, 0.5)

        # Weights sum to 1.0 → average team = 1.0
        raw = (pts_ratio    * 0.35 +
               ypp_ratio    * 0.25 +
               recent_ratio * 0.25 +
               to_ratio     * 0.15)

        sos_adj = 1.0 + (t.sos - 0.5) * self.sos_weight
        inj_adj = 1.0 + t.injury_adj * 0.08

        return raw * sos_adj * inj_adj

    def defensive_rating(self, t: TeamStats) -> float:
        """
        Higher rating = BETTER defense.
        Inverted ratios: (league_avg / team_allowed) > 1 when team allows less than avg.

          pts_ratio    > 1 when allowing fewer pts than avg (good defense)
          ypp_ratio    > 1 when allowing fewer ypp than avg
          recent_ratio > 1 when playing well defensively in recent games
          to_ratio     > 1 when forcing more TOs than avg
        """
        c = self.c
        pts_ratio    = c["league_avg_pts"]       / max(t.pts_per_game_def,   5.0)
        ypp_ratio    = c["league_avg_ypp"]       / max(t.yards_per_play_def, 3.0)
        recent_ratio = c["league_avg_pts"]       / max(t.recent_pts_allowed,  5.0)
        to_ratio     = t.turnovers_forced        / c["league_avg_to_forced"]

        raw = (pts_ratio    * 0.35 +
               ypp_ratio    * 0.25 +
               recent_ratio * 0.25 +
               to_ratio     * 0.15)

        sos_adj = 1.0 + (t.sos - 0.5) * self.sos_weight

        return raw * sos_adj

    def expected_score(
        self,
        offense: TeamStats,
        defense: TeamStats,
        is_home: bool,
        neutral_site: bool,
    ) -> float:
        """
        Expected pts for `offense` against `defense`.

        Formula:
          base = league_avg × off_rating × (1 / def_rating)

        Home field adds/subtracts half the home advantage constant.
        Floor at 3 pts (field goal floor — no zero-score projections).
        """
        off = self.offensive_rating(offense)
        dfn = self.defensive_rating(defense)

        # Core matchup score: scales up when offense > avg, down when defense > avg
        base = self.c["league_avg_pts"] * off * (1.0 / dfn)

        # Home field
        if not neutral_site:
            adj = self.c["home_adv_pts"] * 0.5
            base += adj if is_home else -adj

        return max(base, 3.0)


# ─────────────────────────────────────────────────────────────
# MONTE CARLO SIMULATOR
# ─────────────────────────────────────────────────────────────

class MonteCarloSimulator:
    """
    Simulates a game N times by sampling team scores from
    Normal(expected_pts, score_std_dev).

    Score std_dev represents inherent game-to-game variance
    (turnovers, special teams, situational plays, etc.).

    No negative scores are allowed (floor at 0).
    """

    def __init__(self, league: str):
        self.std = (NFL_CONSTANTS if league == "NFL" else CFB_CONSTANTS)["score_std_dev"]

    def run(
        self,
        exp_a: float,
        exp_b: float,
        spread_line: float,
        total_line: float,
        n: int = 10000,
    ) -> Dict:
        """
        Returns raw simulation counts.

        spread_line convention (positive = A favored):
          A covers  if  (score_a − score_b) > spread_line
          B covers  if  (score_a − score_b) < spread_line
        """
        scores_a = np.maximum(np.random.normal(exp_a, self.std, n), 0)
        scores_b = np.maximum(np.random.normal(exp_b, self.std, n), 0)

        margin = scores_a - scores_b

        return {
            "n":          n,
            "scores_a":   scores_a,
            "scores_b":   scores_b,
            "a_wins":     int(np.sum(scores_a > scores_b)),
            "b_wins":     int(np.sum(scores_b > scores_a)),
            "ties":       int(np.sum(scores_a == scores_b)),
            "a_covers":   int(np.sum(margin > spread_line)),
            "b_covers":   int(np.sum(margin < spread_line)),
            "push_spread":int(np.sum(margin == spread_line)),
            "overs":      int(np.sum((scores_a + scores_b) > total_line)),
            "unders":     int(np.sum((scores_a + scores_b) < total_line)),
            "push_total": int(np.sum((scores_a + scores_b) == total_line)),
        }


# ─────────────────────────────────────────────────────────────
# ODDS UTILITIES
# ─────────────────────────────────────────────────────────────

def american_to_implied(odds: int) -> float:
    """American odds → raw implied probability (%)."""
    if odds < 0:
        return (-odds) / (-odds + 100) * 100
    return 100 / (odds + 100) * 100


def remove_vig(implied_a: float, implied_b: float) -> Tuple[float, float]:
    """
    Strip the sportsbook's juice from raw implied probs.
    Normalizes so both sides sum to 100%.
    """
    total = implied_a + implied_b
    return (implied_a / total * 100), (implied_b / total * 100)


def implied_to_american(prob: float) -> int:
    """Probability (%) → American odds."""
    if prob >= 50:
        return int(-(prob / (100 - prob)) * 100)
    return int((100 - prob) / prob * 100)


# ─────────────────────────────────────────────────────────────
# PREDICTION ENGINE  (main entry point)
# ─────────────────────────────────────────────────────────────

class PredictionEngine:
    """
    Orchestrates the full prediction pipeline:
      1. RatingEngine   → team strength ratings
      2. Expected scores from matchup ratings
      3. MonteCarloSim  → game simulations
      4. Probability    → win / cover / total probs
      5. Edge calc      → model vs market comparison
    """

    def predict(self, matchup: MatchupInput) -> GamePrediction:
        league = matchup.team_a.league
        ratings = RatingEngine(league)
        sim     = MonteCarloSimulator(league)

        # ── Step 1: Ratings ──────────────────────────────────
        off_a = ratings.offensive_rating(matchup.team_a)
        def_a = ratings.defensive_rating(matchup.team_a)
        off_b = ratings.offensive_rating(matchup.team_b)
        def_b = ratings.defensive_rating(matchup.team_b)

        # ── Step 2: Expected scores ───────────────────────────
        exp_a = ratings.expected_score(
            matchup.team_a, matchup.team_b,
            is_home=matchup.team_a_is_home,
            neutral_site=matchup.neutral_site,
        )
        exp_b = ratings.expected_score(
            matchup.team_b, matchup.team_a,
            is_home=not matchup.team_a_is_home,
            neutral_site=matchup.neutral_site,
        )

        # ── Step 3: Simulation ────────────────────────────────
        results = sim.run(
            exp_a, exp_b,
            spread_line=matchup.spread_line,
            total_line=matchup.over_under_line,
            n=matchup.simulations,
        )

        n        = results["n"]
        scores_a = results["scores_a"]
        scores_b = results["scores_b"]

        # ── Step 4: Probabilities ─────────────────────────────
        win_a    = results["a_wins"]  / n * 100
        win_b    = results["b_wins"]  / n * 100
        cover_a  = results["a_covers"] / n * 100
        cover_b  = results["b_covers"] / n * 100
        over_p   = results["overs"]   / n * 100
        under_p  = results["unders"]  / n * 100

        r_a = (np.percentile(scores_a, 10), np.percentile(scores_a, 90))
        r_b = (np.percentile(scores_b, 10), np.percentile(scores_b, 90))

        # ── Step 5: Edge calculation ──────────────────────────
        raw_a = american_to_implied(matchup.team_a_odds)
        raw_b = american_to_implied(matchup.team_b_odds)
        mkt_a, mkt_b = remove_vig(raw_a, raw_b)

        edge_a = win_a - mkt_a
        edge_b = win_b - mkt_b

        return GamePrediction(
            team_a_name          = matchup.team_a.name,
            team_b_name          = matchup.team_b.name,
            team_a_win_prob      = round(win_a,   1),
            team_b_win_prob      = round(win_b,   1),
            projected_pts_a      = round(float(np.mean(scores_a)), 1),
            projected_pts_b      = round(float(np.mean(scores_b)), 1),
            projected_total      = round(float(np.mean(scores_a + scores_b)), 1),
            score_range_a        = (round(r_a[0], 1), round(r_a[1], 1)),
            score_range_b        = (round(r_b[0], 1), round(r_b[1], 1)),
            spread_line          = matchup.spread_line,
            team_a_cover_prob    = round(cover_a, 1),
            team_b_cover_prob    = round(cover_b, 1),
            over_under_line      = matchup.over_under_line,
            over_prob            = round(over_p,  1),
            under_prob           = round(under_p, 1),
            off_rating_a         = round(off_a, 3),
            def_rating_a         = round(def_a, 3),
            off_rating_b         = round(off_b, 3),
            def_rating_b         = round(def_b, 3),
            sportsbook_implied_a = round(mkt_a, 1),
            sportsbook_implied_b = round(mkt_b, 1),
            model_prob_a         = round(win_a, 1),
            model_prob_b         = round(win_b, 1),
            edge_a               = round(edge_a, 1),
            edge_b               = round(edge_b, 1),
            simulations_run      = n,
        )

    def batch_predict(self, matchups: list[MatchupInput]) -> list[GamePrediction]:
        """Run predictions for multiple games at once."""
        return [self.predict(m) for m in matchups]
