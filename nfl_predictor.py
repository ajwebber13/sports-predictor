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
from datetime import datetime
from dataclasses import dataclass
from nfl_data import NFLTeamStats, get_team_stats, get_rest_days
from predictor import NFL_CONSTANTS
from database import get_conn, get_situational_row as _get_situational_row, get_line_movement_adj
from intel_feed import get_matchup_injury_adj

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
                         is_home: bool, rest_days: int,
                         situational_adj: float = 0.0,
                         injury_adj: float = 0.0,
                         line_adj: float = 0.0) -> tuple[float, dict]:
        """
        Returns (final_score, factors) — pure additive like WNBA/CFB.
        Verified via parity check in __main__.
        """
        factors = {}
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

        factors["base_projection"] = round(base, 2)

        home_adj = HOME_FIELD_ADV * 0.5 if is_home else -HOME_FIELD_ADV * 0.5
        factors["home_field"] = round(home_adj, 2)

        if rest_days >= BYE_WEEK_THRESHOLD:
            rest_adj = BYE_WEEK_BONUS
        elif rest_days <= SHORT_WEEK_DAYS:
            rest_adj = SHORT_WEEK_PEN
        else:
            rest_adj = 0.0
        factors["rest"] = round(rest_adj, 2)

        to_adj  = (LEAGUE_AVG_TO - offense.turnovers_given) * 1.5
        to_adj += (offense.turnovers_forced - LEAGUE_AVG_TO) * 1.0
        factors["turnover_margin"] = round(to_adj, 2)

        # Situational (travel/altitude/timezone) — away-team-only,
        # same reasoning as WNBA/MLB/CFB. West-coast-to-east-coast
        # early kickoffs and Denver's altitude are the real NFL cases
        # this covers.
        sit_adj = situational_adj if not is_home else 0.0
        factors["situational"] = round(sit_adj, 2)

        factors["injury"] = round(injury_adj, 2)

        factors["line_movement"] = round(line_adj, 2)

        final_score = max(sum(factors.values()), 6.0)
        return final_score, factors

    def predict(self, home_stats: NFLTeamStats, away_stats: NFLTeamStats,
                spread_line: float = 0.0, over_under: float = 44.0,
                simulations: int = 10000) -> NFLPrediction:

        situational = _get_situational_row(home_stats.team_name, away_stats.team_name, sport="nfl")
        if situational:
            home_rest = situational["home_rest_days"] if situational["home_rest_days"] is not None else get_rest_days(home_stats.team_name)
            away_rest = situational["away_rest_days"] if situational["away_rest_days"] is not None else get_rest_days(away_stats.team_name)
            total_adj = situational["total_adj"] if situational["total_adj"] is not None else 0.0
        else:
            home_rest = get_rest_days(home_stats.team_name)
            away_rest = get_rest_days(away_stats.team_name)
            total_adj = 0.0

        try:
            home_inj_adj, away_inj_adj = get_matchup_injury_adj(
                home_stats.team_name, away_stats.team_name, league="NFL")
        except Exception as e:
            print(f"  [NFL] injury adj fetch failed, defaulting to 0: {e}")
            home_inj_adj, away_inj_adj = 0.0, 0.0

        try:
            home_line_adj, away_line_adj = get_line_movement_adj(
                home_stats.team_name, away_stats.team_name, sport="nfl")
        except Exception as e:
            print(f"  [NFL] line movement fetch failed, defaulting to 0: {e}")
            home_line_adj, away_line_adj = 0.0, 0.0

        exp_home, home_factors = self._expected_score(home_stats, away_stats, is_home=True,  rest_days=home_rest,
                                        situational_adj=total_adj, injury_adj=home_inj_adj, line_adj=home_line_adj)
        exp_away, away_factors = self._expected_score(away_stats, home_stats, is_home=False, rest_days=away_rest,
                                        situational_adj=total_adj, injury_adj=away_inj_adj, line_adj=away_line_adj)

        try:
            from database import save_prediction_factors
            today = datetime.now().strftime("%Y-%m-%d")
            game_id = f"{today}_{away_stats.team_name}_{home_stats.team_name}".replace(" ", "-")
            save_prediction_factors(
                sport="nfl", game_id=game_id,
                home_team=home_stats.team_name, away_team=away_stats.team_name,
                home_score_final=round(exp_home, 2), away_score_final=round(exp_away, 2),
                home_factors=home_factors, away_factors=away_factors,
            )
        except Exception as e:
            print(f"  [NFL] factor logging failed (non-fatal): {e}")

        scores_home = np.maximum(np.random.normal(exp_home, SCORE_STD_DEV, simulations), 0)
        scores_away = np.maximum(np.random.normal(exp_away, SCORE_STD_DEV, simulations), 0)
        margin = scores_home - scores_away
        n = simulations

        home_win = round(float(np.sum(scores_home > scores_away) / n * 100), 1)
        away_win = round(float(np.sum(scores_away > scores_home) / n * 100), 1)
        # Cover condition is margin + spread_line > 0 (see auto_results.py's
        # actual grading formula and mlb_predictor.py's run_line handling)
        # — spread_line is negative for the favorite, so a team laying 14
        # needs margin > 14, not margin > -14.
        home_cov = round(float(np.sum(margin > -spread_line) / n * 100), 1)
        away_cov = round(float(np.sum(margin < -spread_line) / n * 100), 1)
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


def _parity_check_old_style(offense, defense, is_home, rest_days,
                             situational_adj=0.0, injury_adj=0.0, line_adj=0.0):
    """Reference implementation — exact pre-refactor math, parity check only."""
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
    if not is_home:
        base += situational_adj
    base += injury_adj
    base += line_adj
    return max(base, 6.0)


class _SyntheticNFLStats:
    """Minimal stand-in so the parity check runs even out of season."""
    def __init__(self, team_name, pts_per_game, pts_allowed, ypp_off, ypp_def,
                 to_given, to_forced):
        self.team_name = team_name
        self.pts_per_game = pts_per_game
        self.pts_allowed = pts_allowed
        self.yards_per_play_off = ypp_off
        self.yards_per_play_def = ypp_def
        self.turnovers_given = to_given
        self.turnovers_forced = to_forced


if __name__ == "__main__":
    print("Testing NFL prediction engine...")

    syn_home = _SyntheticNFLStats("Test Home", 24.5, 20.0, 5.8, 5.2, 1.0, 1.2)
    syn_away = _SyntheticNFLStats("Test Away", 22.0, 23.5, 5.5, 5.6, 1.2, 0.9)
    engine_for_parity = NFLPredictionEngine()
    new_score, factors = engine_for_parity._expected_score(
        syn_home, syn_away, is_home=True, rest_days=7, situational_adj=0.0, injury_adj=-3.0, line_adj=0.3)
    old_score = _parity_check_old_style(syn_home, syn_away, is_home=True, rest_days=7, injury_adj=-3.0, line_adj=0.3)
    parity_ok = abs(new_score - old_score) < 0.01
    print(f"Parity check: new={new_score:.2f} old={old_score:.2f} -> {'PASS' if parity_ok else 'FAIL — DO NOT SHIP'}")
    print(f"  Factors: {factors}\n")

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
