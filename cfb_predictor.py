"""
cfb_predictor.py
=================
Live CFB prediction model. Same shape as wnba_predictor.py, adapted
for football:
  - No back-to-backs — bye weeks instead (10+ days rest)
  - Turnover margin and yards-per-play drive scoring instead of pace
  - Uses CFB_CONSTANTS from predictor.py so numbers stay consistent
    with the rest of the repo (no forked constants)

Uses live ESPN stats to calculate:
  - Win probability via Monte Carlo simulation
  - Projected score
  - Spread and total coverage probability
  - Bye-week rest adjustment
  - Home field advantage
"""

import numpy as np
from datetime import datetime
from dataclasses import dataclass
from cfb_data import CFBTeamStats, get_rest_days
from database import get_conn, get_situational_row as _get_situational_row
try:
    # Prefer CFBD (real SP+ ratings blended in) if the cfbd package
    # and CFBD_API_KEY are set up. Falls back to plain ESPN inside
    # get_team_stats() itself if CFBD isn't configured or fails.
    from cfbd_api import get_team_stats
except ImportError:
    # cfbd package isn't even installed — just use plain ESPN.
    from cfb_data import get_team_stats
from predictor import CFB_CONSTANTS

# ─────────────────────────────────────────────────────────────
# CONSTANTS (pulled from predictor.py — single source of truth)
# ─────────────────────────────────────────────────────────────

LEAGUE_AVG_PPG     = CFB_CONSTANTS["league_avg_pts"]       # 29.0
LEAGUE_AVG_YPP     = CFB_CONSTANTS["league_avg_ypp"]       # 5.9
LEAGUE_AVG_TO      = CFB_CONSTANTS["league_avg_to_given"]  # 1.5
HOME_FIELD_ADV     = CFB_CONSTANTS["home_adv_pts"]         # 3.0
SCORE_STD_DEV      = CFB_CONSTANTS["score_std_dev"]        # 10.5

BYE_WEEK_THRESHOLD = 10     # days since last game to count as a bye
BYE_WEEK_BONUS     = 1.5    # pts boost coming off a bye
SHORT_WEEK_PEN     = -1.0   # pts penalty for a short week (<6 days — Tue/Wed MACtion)
SHORT_WEEK_DAYS    = 6





# ─────────────────────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────────────────────

@dataclass
class CFBPrediction:
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
    home_home_record:   str
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
            "net_ypp": {
                self.home_team: self.home_net_ypp,
                self.away_team: self.away_net_ypp,
            },
            "records": {
                self.home_team: {"overall": self.home_record, "home": self.home_home_record},
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

class CFBPredictionEngine:

    def _expected_score(
        self,
        offense: CFBTeamStats,
        defense: CFBTeamStats,
        is_home: bool,
        rest_days: int,
        situational_adj: float = 0.0,
    ) -> float:
        """
        Expected points using points-per-game and yards-per-play
        differentials, adjusted for home field, bye weeks, and
        turnover margin. Falls back to advanced_metrics (Elo) if
        it's populated for CFB — mirrors the WNBA predictor's
        try-the-DB-first pattern.
        """
        try:
            from database import get_conn
            conn = get_conn()
            c    = conn.cursor()
            c.execute("""
                SELECT off_rating, def_rating
                FROM advanced_metrics
                WHERE sport = 'cfb' AND team_name = ?
                ORDER BY season DESC LIMIT 1
            """, (offense.team_name,))
            off_row = c.fetchone()
            c.execute("""
                SELECT off_rating, def_rating
                FROM advanced_metrics
                WHERE sport = 'cfb' AND team_name = ?
                ORDER BY season DESC LIMIT 1
            """, (defense.team_name,))
            def_row = c.fetchone()
            conn.close()

            if off_row and def_row and off_row["off_rating"] > 0 and def_row["def_rating"] > 0:
                base = round((off_row["off_rating"] + def_row["def_rating"]) / 2, 1)
            else:
                raise ValueError("No CFB advanced metrics yet")

        except Exception:
            # Fallback: average this offense's scoring with what this
            # defense typically allows (standard matchup projection —
            # NOT a multiplicative ratio, which compounds too hard
            # given how much CFB scoring varies team to team)
            base = (offense.pts_per_game + defense.pts_allowed) / 2
            ypp_gap = (offense.yards_per_play_off - defense.yards_per_play_def)
            base += ypp_gap * 2.0  # each yard/play edge worth ~2 pts

        # Home field
        if is_home:
            base += HOME_FIELD_ADV * 0.5
        else:
            base -= HOME_FIELD_ADV * 0.5

        # Bye week / short week adjustment
        if rest_days >= BYE_WEEK_THRESHOLD:
            base += BYE_WEEK_BONUS
        elif rest_days < SHORT_WEEK_DAYS:
            base += SHORT_WEEK_PEN

        # Turnover margin adjustment
        to_adj = (LEAGUE_AVG_TO - offense.turnovers_given) * 1.5
        to_adj += (offense.turnovers_forced - LEAGUE_AVG_TO) * 1.0
        base += to_adj

        # Situational (travel/altitude/timezone) — away-team-only
        # penalty, same reasoning as WNBA/MLB: it's computed against
        # whoever is traveling, not applied symmetrically. Road trips
        # matter more in CFB than most sports (Boise State hosting a
        # team crossing 3 time zones, altitude for Air Force/Wyoming
        # home games), so this one's worth having even though CFB
        # already had decent rest-day logic on its own.
        if not is_home:
            base += situational_adj

        return max(base, 7.0)

    def predict(
        self,
        home_stats:   CFBTeamStats,
        away_stats:   CFBTeamStats,
        spread_line:  float = 0.0,
        over_under:   float = 52.0,
        simulations:  int   = 10000,
    ) -> CFBPrediction:

        situational = _get_situational_row(home_stats.team_name, away_stats.team_name, sport="cfb")
        if situational:
            home_rest = situational["home_rest_days"] if situational["home_rest_days"] is not None else get_rest_days(home_stats.team_name)
            away_rest = situational["away_rest_days"] if situational["away_rest_days"] is not None else get_rest_days(away_stats.team_name)
            total_adj = situational["total_adj"] if situational["total_adj"] is not None else 0.0
        else:
            home_rest = get_rest_days(home_stats.team_name)
            away_rest = get_rest_days(away_stats.team_name)
            total_adj = 0.0

        exp_home = self._expected_score(home_stats, away_stats, is_home=True,  rest_days=home_rest,
                                        situational_adj=total_adj)
        exp_away = self._expected_score(away_stats, home_stats, is_home=False, rest_days=away_rest,
                                        situational_adj=total_adj)

        # Monte Carlo
        scores_home = np.maximum(np.random.normal(exp_home, SCORE_STD_DEV, simulations), 0)
        scores_away = np.maximum(np.random.normal(exp_away, SCORE_STD_DEV, simulations), 0)
        margin = scores_home - scores_away
        n = simulations

        home_win  = round(float(np.sum(scores_home > scores_away) / n * 100), 1)
        away_win  = round(float(np.sum(scores_away > scores_home) / n * 100), 1)
        home_cov  = round(float(np.sum(margin > spread_line) / n * 100), 1)
        away_cov  = round(float(np.sum(margin < spread_line) / n * 100), 1)
        over_p    = round(float(np.sum((scores_home + scores_away) > over_under) / n * 100), 1)
        under_p   = round(float(np.sum((scores_home + scores_away) < over_under) / n * 100), 1)

        return CFBPrediction(
            home_team        = home_stats.team_name,
            away_team        = away_stats.team_name,
            home_win_prob    = home_win,
            away_win_prob    = away_win,
            projected_home   = round(float(np.mean(scores_home)), 1),
            projected_away   = round(float(np.mean(scores_away)), 1),
            projected_total  = round(float(np.mean(scores_home + scores_away)), 1),
            spread_line      = spread_line,
            home_cover_prob  = home_cov,
            away_cover_prob  = away_cov,
            over_prob        = over_p,
            under_prob       = under_p,
            home_net_ypp     = home_stats.net_yards_per_play,
            away_net_ypp     = away_stats.net_yards_per_play,
            home_rest_days   = home_rest,
            away_rest_days   = away_rest,
            home_record      = f"{home_stats.wins}-{home_stats.losses}",
            away_record      = f"{away_stats.wins}-{away_stats.losses}",
            home_home_record = f"{home_stats.home_wins}-{home_stats.home_losses}",
            away_road_record = f"{away_stats.away_wins}-{away_stats.away_losses}",
            simulations      = simulations,
        )


if __name__ == "__main__":
    print("Testing CFB prediction engine...")
    home = get_team_stats("Georgia")
    away = get_team_stats("Alabama")

    if home and away:
        engine = CFBPredictionEngine()
        pred = engine.predict(home, away, spread_line=-3.5, over_under=51.5)
        print(f"\n{pred.away_team} @ {pred.home_team}")
        print(f"Win Prob: {pred.home_team} {pred.home_win_prob}% | {pred.away_team} {pred.away_win_prob}%")
        print(f"Projected: {pred.projected_home} - {pred.projected_away} (Total: {pred.projected_total})")
        print(f"Records: {pred.home_team} {pred.home_record} (Home: {pred.home_home_record})")
        print(f"         {pred.away_team} {pred.away_record} (Road: {pred.away_road_record})")
        print(f"Rest: {pred.home_team} {pred.home_rest_days}d | {pred.away_team} {pred.away_rest_days}d")
    else:
        print("Could not fetch team stats — check ESPN API or team names in FBS_TEAM_IDS.")
