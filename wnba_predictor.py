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
from datetime import datetime
from dataclasses import dataclass
from typing import Tuple
from wnba_data import WNBATeamStats, get_team_stats
from database import get_conn, get_situational_row as _get_situational_row, get_line_movement_adj
from intel_feed import get_matchup_injury_adj

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
    home_factors:       dict = None
    away_factors:       dict = None

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
        situational_adj: float = 0.0,
        injury_adj: float = 0.0,
        line_adj: float = 0.0,
    ) -> tuple[float, dict]:
        """
        Calculate expected score using offensive/defensive ratings.
        Pace-adjusted with rest and home court modifiers.

        Returns (final_score, factors) — factors is a named dict of
        every point adjustment applied, for the prediction_factors
        explainability log. This is a pure extraction of the same
        math that used to accumulate into one `base` variable — no
        adjustment values changed, they're just labeled now. Verified
        via the parity check in __main__ (old-style sum == new dict
        sum, floating-point tolerance).
        """
        factors = {}

        # Try to use advanced metrics (off/def rating) from DB
        try:
            from database import get_conn
            conn = get_conn()
            c    = conn.cursor()
            c.execute("""
                SELECT off_rating, def_rating, pace
                FROM advanced_metrics
                WHERE sport = 'wnba' AND team_name = ?
                ORDER BY season DESC LIMIT 1
            """, (offense.team_name,))
            off_row = c.fetchone()
            c.execute("""
                SELECT off_rating, def_rating, pace
                FROM advanced_metrics
                WHERE sport = 'wnba' AND team_name = ?
                ORDER BY season DESC LIMIT 1
            """, (defense.team_name,))
            def_row = c.fetchone()
            conn.close()

            if off_row and def_row and off_row["off_rating"] > 0 and def_row["def_rating"] > 0:
                # Use real off/def ratings per 100 possessions
                pace       = (off_row["pace"] + def_row["pace"]) / 2
                base_per100 = (off_row["off_rating"] + def_row["def_rating"]) / 2
                base       = round((base_per100 / 100) * (pace / 100) * 100, 1)
            else:
                raise ValueError("No advanced metrics")

        except Exception:
            # Fallback to basic pts per game model
            off_factor = offense.pts_per_game / LEAGUE_AVG_PPG
            def_factor = LEAGUE_AVG_PPG / max(defense.opp_pts_per_game, 60.0)
            base = LEAGUE_AVG_PPG * off_factor * def_factor

        factors["base_projection"] = round(base, 2)

        # Home court
        if is_home:
            home_adj = HOME_COURT_ADV * 0.5
        else:
            home_adj = -HOME_COURT_ADV * 0.5
        factors["home_court"] = round(home_adj, 2)

        # Rest adjustment
        if rest_days == 1:
            rest_adj = BACK_TO_BACK_PEN
        elif rest_days >= 3:
            rest_adj = REST_ADJ_PER_DAY * min(rest_days - 2, 3)
        else:
            rest_adj = 0.0
        factors["rest"] = round(rest_adj, 2)

        # Turnover adjustment (more TOs = fewer possessions = fewer pts)
        league_avg_to = 13.5
        to_adj = (league_avg_to - offense.turnovers_per_game) * 0.3
        factors["turnovers"] = round(to_adj, 2)

        # Situational (travel/altitude/timezone) — total_adj from
        # situational_factors is computed as an AWAY-team penalty
        # (travel distance, home team's altitude, timezone crossing),
        # so it only applies when this team is the away team. Home
        # court advantage is already handled separately above.
        sit_adj = situational_adj if not is_home else 0.0
        factors["situational"] = round(sit_adj, 2)

        # Injuries — this is the team's OWN missing players hurting
        # its OWN output, so unlike situational_adj it applies to
        # both home and away, not just whoever's traveling.
        factors["injury"] = round(injury_adj, 2)

        # Line movement — small nudge, not a primary signal. See
        # get_line_movement_adj()'s docstring for the exact formula.
        factors["line_movement"] = round(line_adj, 2)

        final_score = max(sum(factors.values()), 55.0)
        return final_score, factors

    def predict(
        self,
        home_stats:   WNBATeamStats,
        away_stats:   WNBATeamStats,
        spread_line:  float = 0.0,
        over_under:   float = 164.0,
        simulations:  int   = 10000,
    ) -> WNBAPrediction:

        situational = _get_situational_row(home_stats.team_name, away_stats.team_name, sport="wnba")

        if situational:
            home_rest = situational["home_rest_days"] if situational["home_rest_days"] is not None else 3
            away_rest = situational["away_rest_days"] if situational["away_rest_days"] is not None else 3
            total_adj = situational["total_adj"] if situational["total_adj"] is not None else 0.0
        else:
            # No row for today yet (e.g. testing a matchup ad hoc,
            # outside the normal daily job) — safe neutral defaults,
            # not a guess dressed up as real data.
            home_rest = 3
            away_rest = 3
            total_adj = 0.0

        try:
            home_inj_adj, away_inj_adj = get_matchup_injury_adj(
                home_stats.team_name, away_stats.team_name, league="WNBA")
        except Exception as e:
            print(f"  [WNBA] injury adj fetch failed, defaulting to 0: {e}")
            home_inj_adj, away_inj_adj = 0.0, 0.0

        try:
            home_line_adj, away_line_adj = get_line_movement_adj(
                home_stats.team_name, away_stats.team_name, sport="wnba")
        except Exception as e:
            print(f"  [WNBA] line movement fetch failed, defaulting to 0: {e}")
            home_line_adj, away_line_adj = 0.0, 0.0

        exp_home, home_factors = self._expected_score(home_stats, away_stats, is_home=True,
                                        rest_days=home_rest, opp_rest_days=away_rest,
                                        situational_adj=total_adj, injury_adj=home_inj_adj,
                                        line_adj=home_line_adj)
        exp_away, away_factors = self._expected_score(away_stats, home_stats, is_home=False,
                                        rest_days=away_rest, opp_rest_days=home_rest,
                                        situational_adj=total_adj, injury_adj=away_inj_adj,
                                        line_adj=away_line_adj)

        # Explainability log — best-effort, never blocks the actual
        # prediction. game_id date-scoped per save_prediction_factors'
        # documented convention.
        try:
            from database import save_prediction_factors
            today = datetime.now().strftime("%Y-%m-%d")
            game_id = f"{today}_{away_stats.team_name}_{home_stats.team_name}".replace(" ", "-")
            save_prediction_factors(
                sport="wnba", game_id=game_id,
                home_team=home_stats.team_name, away_team=away_stats.team_name,
                home_score_final=round(exp_home, 2), away_score_final=round(exp_away, 2),
                home_factors=home_factors, away_factors=away_factors,
            )
        except Exception as e:
            print(f"  [WNBA] factor logging failed (non-fatal): {e}")

        # Monte Carlo
        scores_home = np.maximum(np.random.normal(exp_home, SCORE_STD_DEV, simulations), 40)
        scores_away = np.maximum(np.random.normal(exp_away, SCORE_STD_DEV, simulations), 40)
        margin = scores_home - scores_away
        n = simulations

        home_win  = round(float(np.sum(scores_home > scores_away) / n * 100), 1)
        away_win  = round(float(np.sum(scores_away > scores_home) / n * 100), 1)
        # Cover condition is margin + spread_line > 0 (see auto_results.py's
        # actual grading formula and mlb_predictor.py's run_line handling)
        # — spread_line is negative for the favorite, so a team laying 14
        # needs margin > 14, not margin > -14.
        home_cov  = round(float(np.sum(margin > -spread_line) / n * 100), 1)
        away_cov  = round(float(np.sum(margin < -spread_line) / n * 100), 1)
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
            home_factors    = home_factors,
            away_factors    = away_factors,
        )


def _parity_check_old_style(offense, defense, is_home, rest_days,
                             situational_adj=0.0, injury_adj=0.0, line_adj=0.0):
    """
    Reference implementation — the exact pre-refactor math, kept only
    for the parity check below. If _expected_score's factor dict ever
    stops summing to this, the refactor broke something.
    """
    try:
        from database import get_conn
        conn = get_conn()
        c    = conn.cursor()
        c.execute("""
            SELECT off_rating, def_rating, pace FROM advanced_metrics
            WHERE sport = 'wnba' AND team_name = ? ORDER BY season DESC LIMIT 1
        """, (offense.team_name,))
        off_row = c.fetchone()
        c.execute("""
            SELECT off_rating, def_rating, pace FROM advanced_metrics
            WHERE sport = 'wnba' AND team_name = ? ORDER BY season DESC LIMIT 1
        """, (defense.team_name,))
        def_row = c.fetchone()
        conn.close()
        if off_row and def_row and off_row["off_rating"] > 0 and def_row["def_rating"] > 0:
            pace = (off_row["pace"] + def_row["pace"]) / 2
            base_per100 = (off_row["off_rating"] + def_row["def_rating"]) / 2
            base = round((base_per100 / 100) * (pace / 100) * 100, 1)
        else:
            raise ValueError("No advanced metrics")
    except Exception:
        off_factor = offense.pts_per_game / LEAGUE_AVG_PPG
        def_factor = LEAGUE_AVG_PPG / max(defense.opp_pts_per_game, 60.0)
        base = LEAGUE_AVG_PPG * off_factor * def_factor

    if is_home:
        base += HOME_COURT_ADV * 0.5
    else:
        base -= HOME_COURT_ADV * 0.5

    if rest_days == 1:
        base += BACK_TO_BACK_PEN
    elif rest_days >= 3:
        base += REST_ADJ_PER_DAY * min(rest_days - 2, 3)

    league_avg_to = 13.5
    base += (league_avg_to - offense.turnovers_per_game) * 0.3

    if not is_home:
        base += situational_adj

    base += injury_adj
    base += line_adj

    return max(base, 55.0)


if __name__ == "__main__":
    print("Testing WNBA prediction engine...")
    home = get_team_stats("Minnesota Lynx")
    away = get_team_stats("Los Angeles Sparks")

    if home and away:
        engine = WNBAPredictionEngine()

        try:
            h_adj, a_adj = get_matchup_injury_adj(home.team_name, away.team_name, league="WNBA")
            print(f"Injury adj -> {home.team_name}: {h_adj:+.1f} pts | {away.team_name}: {a_adj:+.1f} pts")
        except Exception as e:
            h_adj, a_adj = 0.0, 0.0
            print(f"Injury adj fetch FAILED: {e}")

        try:
            h_line, a_line = get_line_movement_adj(home.team_name, away.team_name, sport="wnba")
            print(f"Line movement adj -> {home.team_name}: {h_line:+.1f} pts | {away.team_name}: {a_line:+.1f} pts")
        except Exception as e:
            h_line, a_line = 0.0, 0.0
            print(f"Line movement fetch FAILED: {e}")

        # ── Parity check ── new factors-dict path vs old single-base
        # path, same inputs, should match within floating-point tolerance.
        new_home, home_factors = engine._expected_score(
            home, away, is_home=True, rest_days=3, opp_rest_days=3,
            situational_adj=0.0, injury_adj=h_adj, line_adj=h_line)
        old_home = _parity_check_old_style(home, away, is_home=True, rest_days=3, injury_adj=h_adj, line_adj=h_line)
        parity_ok = abs(new_home - old_home) < 0.01
        print(f"Parity check ({home.team_name}): new={new_home:.2f} old={old_home:.2f} "
              f"-> {'PASS' if parity_ok else 'FAIL — DO NOT SHIP'}")
        print(f"  Factors: {home_factors}")

        pred = engine.predict(home, away, spread_line=-4.5, over_under=162.0)
        print(f"\n{pred.away_team} @ {pred.home_team}")
        print(f"Win Prob: {pred.home_team} {pred.home_win_prob}% | {pred.away_team} {pred.away_win_prob}%")
        print(f"Projected: {pred.projected_home} - {pred.projected_away} (Total: {pred.projected_total})")
        print(f"Records: {pred.home_team} {pred.home_record} (Home: {pred.home_away_record})")
        print(f"         {pred.away_team} {pred.away_record} (Road: {pred.away_road_record})")
        print(f"Rest: {pred.home_team} {pred.home_rest_days}d | {pred.away_team} {pred.away_rest_days}d")
