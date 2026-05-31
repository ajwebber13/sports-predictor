"""
wnba_predictor.py
==================
Possession-based WNBA prediction model.

Uses live ESPN stats to calculate:
  - Win probability via Monte Carlo simulation
  - Projected score
  - Spread and total coverage probability
  - Rest and travel adjustments
  - Home court advantage
"""

import numpy as np
from dataclasses import dataclass
from typing import Tuple
from wnba_data import WNBATeamStats, get_team_stats, get_rest_days

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

LEAGUE_AVG_PACE    = 80.0   # possessions per game
LEAGUE_AVG_PPG     = 82.0   # points per game
HOME_COURT_ADV     = 3.2    # point advantage for home team
REST_ADJ_PER_DAY   = 0.4    # pts per extra rest day (up to 3 days)
BACK_TO_BACK_PEN   = -2.5   # pts penalty for back to back
SCORE_STD_DEV      = 10.5   # simulation standard deviation


# ─────────────────────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────────────────────

@dataclass
class WNBAPrediction:
    home_team:          str
    away_team:          str
    home_win_prob:      float
    away_win_prob:      float
    projected_home:     float
    projected_away:     float
    projected_total:    float
    spread_line:        float
    home_cover_prob:    float
    away_cover_prob:    float
    over_prob:          float
    under_prob:         float
    home_net_rating:    float
    away_net_rating:    float
    home_rest_days:     int
    away_rest_days:     int
    home_record:        str
    away_record:        str
    home_away_record:   str
    away_road_record:   str
    simulations:        int

    def to_dict(self) -> dict:
        return {
            "game":           f"{self.away_team} @ {self.home_team}",
            "home_win_prob":  self.home_win_prob,
            "away_win_prob":  self.away_win_prob,
            "projected_score": {
                self.home_team: self.projected_home,
                self.away_team: self.projected_away,
                "total":        self.projected_total,
            },
            "spread":         self.spread_line,
            "home_cover":     self.home_cover_prob,
            "over_prob":      self.over_prob,
            "under_prob":     self.under_prob,
            "net_ratings": {
                self.home_team: self.home_net_rating,
                self.away_team: self.away_net_rating,
            },
            "records": {
                self.home_team: {"overall": self.home_record, "home": self.home_away_record},
                self.away_team: {"overall": self.away_record, "road": self.away_road_record},
            },
            "rest": {
                self.home_team: self.home_rest_days,
                self.away_team: self.away_rest_days,
            },
            "simulations": self.simulations,
        }


# ─────────────────────────────────────────────────────────────
# PREDICTION ENGINE
# ─────────────────────────────────────────────────────────────

class WNBAPredictionEngine:

    def _expected_score(
        self,
        offense: WNBATeamStats,
        defense: WNBATeamStats,
        is_home: bool,
        rest_days: int,
        opp_rest_days: int,
    ) -> float:
        """
        Calculate expected score using offensive/defensive ratings.
        Pace-adjusted with rest and home court modifiers.
        """
        # Base: blend offensive output vs defensive suppression
        off_factor = offense.pts_per_game / LEAGUE_AVG_PPG
        def_factor = LEAGUE_AVG_PPG / max(defense.opp_pts_per_game, 60.0)
        base = LEAGUE_AVG_PPG * off_factor * def_factor

        # Home court
        if is_home:
            base += HOME_COURT_ADV * 0.5
        else:
            base -= HOME_COURT_ADV * 0.5

        # Rest adjustment
        if rest_days == 1:
            base += BACK_TO_BACK_PEN
        elif rest_days >= 3:
            base += REST_ADJ_PER_DAY * min(rest_days - 2, 3)

        # Turnover adjustment (more TOs = fewer possessions = fewer pts)
        league_avg_to = 13.5
        to_adj = (league_avg_to - offense.turnovers_per_game) * 0.3
        base += to_adj

        return max(base, 55.0)

    def predict(
        self,
        home_stats:   WNBATeamStats,
        away_stats:   WNBATeamStats,
        spread_line:  float = 0.0,
        over_under:   float = 164.0,
        simulations:  int   = 10000,
    ) -> WNBAPrediction:

        home_rest = get_rest_days(home_stats.team_name)
        away_rest = get_rest_days(away_stats.team_name)

        exp_home = self._expected_score(home_stats, away_stats, is_home=True,
                                        rest_days=home_rest, opp_rest_days=away_rest)
        exp_away = self._expected_score(away_stats, home_stats, is_home=False,
                                        rest_days=away_rest, opp_rest_days=home_rest)

        # Monte Carlo
        scores_home = np.maximum(np.random.normal(exp_home, SCORE_STD_DEV, simulations), 40)
        scores_away = np.maximum(np.random.normal(exp_away, SCORE_STD_DEV, simulations), 40)
        margin = scores_home - scores_away
        n = simulations

        home_win  = round(float(np.sum(scores_home > scores_away) / n * 100), 1)
        away_win  = round(float(np.sum(scores_away > scores_home) / n * 100), 1)
        home_cov  = round(float(np.sum(margin > spread_line) / n * 100), 1)
        away_cov  = round(float(np.sum(margin < spread_line) / n * 100), 1)
        over_p    = round(float(np.sum((scores_home + scores_away) > over_under) / n * 100), 1)
        under_p   = round(float(np.sum((scores_home + scores_away) < over_under) / n * 100), 1)

        return WNBAPrediction(
            home_team       = home_stats.team_name,
            away_team       = away_stats.team_name,
            home_win_prob   = home_win,
            away_win_prob   = away_win,
            projected_home  = round(float(np.mean(scores_home)), 1),
            projected_away  = round(float(np.mean(scores_away)), 1),
            projected_total = round(float(np.mean(scores_home + scores_away)), 1),
            spread_line     = spread_line,
            home_cover_prob = home_cov,
            away_cover_prob = away_cov,
            over_prob       = over_p,
            under_prob      = under_p,
            home_net_rating = home_stats.net_rating,
            away_net_rating = away_stats.net_rating,
            home_rest_days  = home_rest,
            away_rest_days  = away_rest,
            home_record     = f"{home_stats.wins}-{home_stats.losses}",
            away_record     = f"{away_stats.wins}-{away_stats.losses}",
            home_away_record = f"{home_stats.home_wins}-{home_stats.home_losses}",
            away_road_record = f"{away_stats.away_wins}-{away_stats.away_losses}",
            simulations     = simulations,
        )


if __name__ == "__main__":
    print("Testing WNBA prediction engine...")
    home = get_team_stats("Las Vegas Aces")
    away = get_team_stats("Golden State Valkyries")

    if home and away:
        engine = WNBAPredictionEngine()
        pred = engine.predict(home, away, spread_line=-4.5, over_under=162.0)
        print(f"\n{pred.away_team} @ {pred.home_team}")
        print(f"Win Prob: {pred.home_team} {pred.home_win_prob}% | {pred.away_team} {pred.away_win_prob}%")
        print(f"Projected: {pred.projected_home} - {pred.projected_away} (Total: {pred.projected_total})")
        print(f"Records: {pred.home_team} {pred.home_record} (Home: {pred.home_away_record})")
        print(f"         {pred.away_team} {pred.away_record} (Road: {pred.away_road_record})")
        print(f"Rest: {pred.home_team} {pred.home_rest_days}d | {pred.away_team} {pred.away_rest_days}d")
