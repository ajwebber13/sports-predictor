"""
nfl_predictor.py
=================
Live NFL prediction model. Same shape as cfb_predictor.py:
  - Uses NFL_CONSTANTS from predictor.py (home_adv 2.5, std_dev 9.5)
  - Bye weeks (13+ days) give a rest bonus
  - Short weeks (Thursday games, ~4 days rest) get a real penalty —
    bigger deal in the NFL than CFB, since short-week prep with an
    NFL-caliber game plan is a well-documented disadvantage
  - Turnover margin and yards-per-play drive scoring
"""

import numpy as np
from dataclasses import dataclass
from nfl_data import NFLTeamStats, get_team_stats, get_rest_days
from predictor import NFL_CONSTANTS

LEAGUE_AVG_PPG  = NFL_CONSTANTS["league_avg_pts"]       # 23.0
LEAGUE_AVG_TO   = NFL_CONSTANTS["league_avg_to_given"]  # 1.2
HOME_FIELD_ADV  = NFL_CONSTANTS["home_adv_pts"]         # 2.5
SCORE_STD_DEV   = NFL_CONSTANTS["score_std_dev"]        # 9.5

BYE_WEEK_THRESHOLD  = 12    # days since last game to count as a bye
BYE_WEEK_BONUS      = 1.0   # NFL bye bonus is smaller than CFB's — less
                             # correlation between rest and NFL performance
SHORT_WEEK_DAYS     = 5     # Thursday game after a Sunday game ≈ 4 days
SHORT_WEEK_PEN       = -2.0 # bigger penalty than CFB — well-documented
                             # Thursday Night Football scoring dip


@dataclass
class NFLPrediction:
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
    home_net_ypp:       float
    away_net_ypp:       float
    home_rest_days:     int
    away_rest_days:     int
    home_record:        str
    away_record:        str
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
            "net_ypp": {
                self.home_team: self.home_net_ypp,
                self.away_team: self.away_net_ypp,
            },
            "records": {
                self.home_team: self.home_record,
                self.away_team: self.away_record,
            },
            "rest": {
                self.home_team: self.home_rest_days,
                self.away_team: self.away_rest_days,
            },
            "simulations": self.simulations,
        }


class NFLPredictionEngine:

    def _expected_score(self, offense: NFLTeamStats, defense: NFLTeamStats,
                         is_home: bool, rest_days: int) -> float:
        try:
            from database import get_conn
            conn = get_conn()
            c    = conn.cursor()
            c.execute("""
                SELECT off_rating, def_rating FROM advanced_metrics
                WHERE sport = 'nfl' AND team_name = ?
                ORDER BY season DESC LIMIT 1
            """, (offense.team_name,))
            off_row = c.fetchone()
            c.execute("""
                SELECT off_rating, def_rating FROM advanced_metrics
                WHERE sport = 'nfl' AND team_name = ?
                ORDER BY season DESC LIMIT 1
            """, (defense.team_name,))
            def_row = c.fetchone()
            conn.close()

            if off_row and def_row and off_row["off_rating"] > 0 and def_row["def_rating"] > 0:
                base = round((off_row["off_rating"] + def_row["def_rating"]) / 2, 1)
            else:
                raise ValueError("No NFL advanced metrics yet")

        except Exception:
            base = (offense.pts_per_game + defense.pts_allowed) / 2
            ypp_gap = (offense.yards_per_play_off - defense.yards_per_play_def)
            base += ypp_gap * 2.0

        if is_home:
            base += HOME_FIELD_ADV * 0.5
        else:
            base -= HOME_FIELD_ADV * 0.5

        if rest_days >= BYE_WEEK_THRESHOLD:
            base += BYE_WEEK_BONUS
        elif rest_days <= SHORT_WEEK_DAYS:
            base += SHORT_WEEK_PEN

        to_adj  = (LEAGUE_AVG_TO - offense.turnovers_given) * 1.5
        to_adj += (offense.turnovers_forced - LEAGUE_AVG_TO) * 1.0
        base += to_adj

        return max(base, 6.0)

    def predict(self, home_stats: NFLTeamStats, away_stats: NFLTeamStats,
                spread_line: float = 0.0, over_under: float = 44.0,
                simulations: int = 10000) -> NFLPrediction:

        home_rest = get_rest_days(home_stats.team_name)
        away_rest = get_rest_days(away_stats.team_name)

        exp_home = self._expected_score(home_stats, away_stats, is_home=True,  rest_days=home_rest)
        exp_away = self._expected_score(away_stats, home_stats, is_home=False, rest_days=away_rest)

        scores_home = np.maximum(np.random.normal(exp_home, SCORE_STD_DEV, simulations), 0)
        scores_away = np.maximum(np.random.normal(exp_away, SCORE_STD_DEV, simulations), 0)
        margin = scores_home - scores_away
        n = simulations

        home_win = round(float(np.sum(scores_home > scores_away) / n * 100), 1)
        away_win = round(float(np.sum(scores_away > scores_home) / n * 100), 1)
        home_cov = round(float(np.sum(margin > spread_line) / n * 100), 1)
        away_cov = round(float(np.sum(margin < spread_line) / n * 100), 1)
        over_p   = round(float(np.sum((scores_home + scores_away) > over_under) / n * 100), 1)
        under_p  = round(float(np.sum((scores_home + scores_away) < over_under) / n * 100), 1)

        return NFLPrediction(
            home_team=home_stats.team_name, away_team=away_stats.team_name,
            home_win_prob=home_win, away_win_prob=away_win,
            projected_home=round(float(np.mean(scores_home)), 1),
            projected_away=round(float(np.mean(scores_away)), 1),
            projected_total=round(float(np.mean(scores_home + scores_away)), 1),
            spread_line=spread_line,
            home_cover_prob=home_cov, away_cover_prob=away_cov,
            over_prob=over_p, under_prob=under_p,
            home_net_ypp=home_stats.net_yards_per_play,
            away_net_ypp=away_stats.net_yards_per_play,
            home_rest_days=home_rest, away_rest_days=away_rest,
            home_record=f"{home_stats.wins}-{home_stats.losses}",
            away_record=f"{away_stats.wins}-{away_stats.losses}",
            simulations=simulations,
        )


if __name__ == "__main__":
    print("Testing NFL prediction engine...")
    home = get_team_stats("Kansas City Chiefs")
    away = get_team_stats("Buffalo Bills")

    if home and away:
        engine = NFLPredictionEngine()
        pred = engine.predict(home, away, spread_line=-2.5, over_under=47.5)
        print(f"\n{pred.away_team} @ {pred.home_team}")
        print(f"Win Prob: {pred.home_team} {pred.home_win_prob}% | {pred.away_team} {pred.away_win_prob}%")
        print(f"Projected: {pred.projected_home} - {pred.projected_away} (Total: {pred.projected_total})")
        print(f"Records: {pred.home_team} {pred.home_record} | {pred.away_team} {pred.away_record}")
        print(f"Rest: {pred.home_team} {pred.home_rest_days}d | {pred.away_team} {pred.away_rest_days}d")
    else:
        print("Could not fetch team stats.")
