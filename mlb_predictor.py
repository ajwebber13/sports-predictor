"""
mlb_predictor.py
Live MLB prediction engine — mirrors cfb_predictor.py / nfl_predictor.py structure,
with Poisson-based scoring instead of normal distribution (baseball scores are
low, discrete, and can't go negative — normal distribution breaks down here).
"""

import numpy as np
from datetime import datetime
from mlb_data import (
    get_mlb_events, get_team_stats, get_starting_pitcher, get_pitcher_stats,
    get_team_record, get_team_injuries, get_team_rest_days,
    get_run_line_odds, get_total_odds,
)
from mlb_weather import get_stadium_weather, get_weather_adj
from mlb_h2h import get_h2h_record, get_h2h_adj
from mlb_matchup import get_team_vs_pitcher, get_matchup_adj
from database import get_conn, get_situational_row as _get_situational_row, get_line_movement_adj
from intel_feed import get_matchup_injury_adj

MLB_CONSTANTS = {
    "home_adv": 0.35,      # home teams average ~0.35 more runs/game than road teams
    "std_dev": 3.0,         # kept for reference/logging, not used directly in the sim
    "home_win_pct": 0.535,  # baseline to sanity-check model output against
}

SIMS = 10000

RUN_VARIANCE_MULTIPLIER = 1.6

# Model uncertainty: how many runs our OWN projection could plausibly
# be off by (separate from real single-game scoring variance, which
# RUN_VARIANCE_MULTIPLIER already covers). Starting value based on
# typical MLB run-projection error in public models — NOT yet fit to
# Drew's own graded picks (no historical home_runs_proj/away_runs_proj
# stored to fit against). Treat as a starting point, re-tune after
# 2-3 weeks of live data once save_prediction_factors also logs the
# final projected runs (see logging note at the bottom of this patch).
RUN_PROJECTION_UNCERTAINTY = 0.5


def _negbinom_params(mean, variance_multiplier=RUN_VARIANCE_MULTIPLIER):
    """
    Now accepts either a scalar or a numpy array for `mean` — needed
    because simulate_game() below now draws a different "true" mean
    per simulation (model uncertainty), not one fixed mean for all
    10,000 sims.
    """
    mean = np.maximum(mean, 0.01)
    variance = mean * variance_multiplier
    variance = np.where(variance <= mean, mean * 1.01, variance)
    p = mean / variance
    n = mean * p / (1 - p)
    return n, p



def project_runs(team_stats, pitcher_stats, is_home, weather_adj=1.0, situational_adj=0.0, injury_adj=0.0, line_adj=0.0, h2h_adj=0.0, matchup_adj=0.0):
    factors = {}

    base = team_stats.get("runs_per_game", 4.5)
    factors["base_runs_per_game"] = round(base, 3)

    home_adj = MLB_CONSTANTS["home_adv"] / 2 if is_home else -MLB_CONSTANTS["home_adv"] / 2
    factors["home_away_adj"] = round(home_adj, 3)
    base += home_adj

    if pitcher_stats:
        era = pitcher_stats.get("era", 4.20)
        whip = pitcher_stats.get("whip", 1.30)
        era_factor = era / 4.20
        whip_factor = whip / 1.30
        combined_factor = (era_factor * 0.7) + (whip_factor * 0.3)
        combined_factor = max(0.75, min(1.25, combined_factor))
    else:
        combined_factor = 1.0
    factors["pitcher_factor"] = round(combined_factor, 3)
    base *= combined_factor

    factors["weather_factor"] = round(weather_adj, 3)
    base *= weather_adj

    sit_adj = situational_adj if not is_home else 0.0
    factors["situational"] = round(sit_adj, 3)
    base += sit_adj

    factors["injury"] = round(injury_adj, 3)
    base += injury_adj

    factors["line_movement"] = round(line_adj, 3)
    base += line_adj

    factors["h2h"] = round(h2h_adj, 3)
    base += h2h_adj

    factors["matchup"] = round(matchup_adj, 3)
    base += matchup_adj

    final = max(base, 0.5)
    return final, factors


def simulate_game(home_runs_proj, away_runs_proj, sims=SIMS, run_line=None, total_line=None):
    # Stage 1: how much could our OWN projection be off by? Draw a
    # different "true" mean per simulation instead of trusting the
    # single projected number for all 10,000 sims. This is the missing
    # piece that was making high-confidence picks overconfident — see
    # patch notes above.
    home_true_means = np.maximum(
        np.random.normal(home_runs_proj, RUN_PROJECTION_UNCERTAINTY, sims), 0.1
    )
    away_true_means = np.maximum(
        np.random.normal(away_runs_proj, RUN_PROJECTION_UNCERTAINTY, sims), 0.1
    )

    # Stage 2: given that game's "true" mean, how much does the actual
    # score vary around it? (unchanged negative binomial logic, now
    # parameterized per-simulation instead of once for the whole batch)
    home_n, home_p = _negbinom_params(home_true_means)
    away_n, away_p = _negbinom_params(away_true_means)

    home_scores = np.random.negative_binomial(home_n, home_p)
    away_scores = np.random.negative_binomial(away_n, away_p)

    ties = home_scores == away_scores
    while ties.sum() > 0:
        idx = np.where(ties)[0]
        home_scores[idx] = np.random.negative_binomial(home_n[idx], home_p[idx])
        away_scores[idx] = np.random.negative_binomial(away_n[idx], away_p[idx])
        ties = home_scores == away_scores

    home_wins = np.sum(home_scores > away_scores)
    win_prob = home_wins / sims

    avg_home_score = np.mean(home_scores)
    avg_away_score = np.mean(away_scores)

    result = {
        "home_win_prob": float(round(win_prob, 4)),
        "away_win_prob": float(round(1 - win_prob, 4)),
        "proj_home_runs": float(round(avg_home_score, 1)),
        "proj_away_runs": float(round(avg_away_score, 1)),
        "proj_total_runs": float(round(avg_home_score + avg_away_score, 1)),
    }

    if run_line is not None:
        margin = home_scores - away_scores
        home_cover = np.sum(margin > -run_line) / sims
        away_cover = np.sum(margin < -run_line) / sims
        result["home_cover_prob"] = float(round(home_cover * 100, 1))
        result["away_cover_prob"] = float(round(away_cover * 100, 1))
    else:
        result["home_cover_prob"] = None
        result["away_cover_prob"] = None

    if total_line is not None:
        totals = home_scores + away_scores
        over_prob = np.sum(totals > total_line) / sims
        under_prob = np.sum(totals < total_line) / sims
        result["over_prob"] = float(round(over_prob * 100, 1))
        result["under_prob"] = float(round(under_prob * 100, 1))
    else:
        result["over_prob"] = None
        result["under_prob"] = None

    return result


def predict_game(event, include_matchup=True):
    competitors = event["competitions"][0]["competitors"]
    home_comp = next(c for c in competitors if c["homeAway"] == "home")
    away_comp = next(c for c in competitors if c["homeAway"] == "away")

    home_team = home_comp["team"]["displayName"]
    away_team = away_comp["team"]["displayName"]
    home_id = home_comp["team"]["id"]
    away_id = away_comp["team"]["id"]

    home_stats = get_team_stats(home_team)
    away_stats = get_team_stats(away_team)

    pitchers = get_starting_pitcher(event)
    home_pitcher_stats = get_pitcher_stats(pitchers["away"])
    away_pitcher_stats = get_pitcher_stats(pitchers["home"])

    weather = get_stadium_weather(home_team)
    weather_adj = get_weather_adj(weather)

    situational = _get_situational_row(home_team, away_team, sport="mlb")
    if situational:
        home_rest = situational["home_rest_days"] if situational["home_rest_days"] is not None else get_team_rest_days(home_id)
        away_rest = situational["away_rest_days"] if situational["away_rest_days"] is not None else get_team_rest_days(away_id)
        total_adj = situational["total_adj"] if situational["total_adj"] is not None else 0.0
    else:
        home_rest = get_team_rest_days(home_id)
        away_rest = get_team_rest_days(away_id)
        total_adj = 0.0

    try:
        home_inj_adj, away_inj_adj = get_matchup_injury_adj(home_team, away_team, league="MLB")
    except Exception as e:
        print(f"  [MLB] injury adj fetch failed, defaulting to 0: {e}")
        home_inj_adj, away_inj_adj = 0.0, 0.0

    try:
        home_line_adj, away_line_adj = get_line_movement_adj(home_team, away_team, sport="mlb")
    except Exception as e:
        print(f"  [MLB] line movement fetch failed, defaulting to 0: {e}")
        home_line_adj, away_line_adj = 0.0, 0.0

    try:
        h2h_record = get_h2h_record(home_id, home_team, away_team)
        home_h2h_adj = get_h2h_adj(h2h_record)
        away_h2h_adj = -home_h2h_adj
    except Exception as e:
        print(f"  [MLB] H2H fetch failed, defaulting to 0: {e}")
        home_h2h_adj, away_h2h_adj = 0.0, 0.0

    if include_matchup:
        try:
            away_pitcher_name = pitchers["away"].get("athlete", {}).get("displayName", "") if pitchers["away"] else ""
            home_pitcher_name = pitchers["home"].get("athlete", {}).get("displayName", "") if pitchers["home"] else ""

            home_matchup = get_team_vs_pitcher(home_team, away_pitcher_name)
            away_matchup = get_team_vs_pitcher(away_team, home_pitcher_name)

            home_matchup_adj = get_matchup_adj(home_matchup)
            away_matchup_adj = get_matchup_adj(away_matchup)
        except Exception as e:
            print(f"  [MLB] matchup fetch failed, defaulting to 0: {e}")
            home_matchup_adj, away_matchup_adj = 0.0, 0.0
    else:
        home_matchup_adj, away_matchup_adj = 0.0, 0.0

    home_runs_proj, home_factors = project_runs(home_stats, home_pitcher_stats, is_home=True, weather_adj=weather_adj, injury_adj=home_inj_adj, line_adj=home_line_adj, h2h_adj=home_h2h_adj, matchup_adj=home_matchup_adj)
    away_runs_proj, away_factors = project_runs(away_stats, away_pitcher_stats, is_home=False, weather_adj=weather_adj, situational_adj=total_adj, injury_adj=away_inj_adj, line_adj=away_line_adj, h2h_adj=away_h2h_adj, matchup_adj=away_matchup_adj)

    try:
        from database import save_prediction_factors
        today = datetime.now().strftime("%Y-%m-%d")
        game_id = f"{today}_{away_team}_{home_team}".replace(" ", "-")
        save_prediction_factors(
            sport="mlb", game_id=game_id,
            home_team=home_team, away_team=away_team,
            home_score_final=round(home_runs_proj, 2), away_score_final=round(away_runs_proj, 2),
            home_factors=home_factors, away_factors=away_factors,
        )
    except Exception as e:
        print(f"  [MLB] factor logging failed (non-fatal): {e}")

    run_line_odds = get_run_line_odds(event)
    total_odds = get_total_odds(event)

    result = simulate_game(
        home_runs_proj, away_runs_proj,
        run_line=run_line_odds["home_line"] if run_line_odds else None,
        total_line=total_odds["line"] if total_odds else None,
    )
    result["home_team"] = home_team
    result["away_team"] = away_team
    result["weather"] = weather.get("conditions", "unknown")
    result["home_factors"] = home_factors
    result["away_factors"] = away_factors

    result["home_record"] = get_team_record(home_comp)
    result["away_record"] = get_team_record(away_comp)
    result["home_injuries"] = get_team_injuries(home_comp)
    result["away_injuries"] = get_team_injuries(away_comp)
    result["home_rest"] = home_rest
    result["away_rest"] = away_rest

    result["posted_run_line"] = run_line_odds["home_line"] if run_line_odds else None
    result["run_line_home_odds"] = run_line_odds["home_odds"] if run_line_odds else None
    result["run_line_away_odds"] = run_line_odds["away_odds"] if run_line_odds else None
    result["posted_total"] = total_odds["line"] if total_odds else None
    result["total_over_odds"] = total_odds["over_odds"] if total_odds else None
    result["total_under_odds"] = total_odds["under_odds"] if total_odds else None

    return result


def _parity_check_old_style(team_stats, pitcher_stats, is_home, weather_adj=1.0,
                             situational_adj=0.0, injury_adj=0.0, line_adj=0.0):
    base = team_stats.get("runs_per_game", 4.5)
    if is_home:
        base += MLB_CONSTANTS["home_adv"] / 2
    else:
        base -= MLB_CONSTANTS["home_adv"] / 2
    if pitcher_stats:
        era = pitcher_stats.get("era", 4.20)
        whip = pitcher_stats.get("whip", 1.30)
        era_factor = era / 4.20
        whip_factor = whip / 1.30
        combined_factor = (era_factor * 0.7) + (whip_factor * 0.3)
        base *= combined_factor
    base *= weather_adj
    if not is_home:
        base += situational_adj
    base += injury_adj
    base += line_adj
    return max(base, 0.5)


if __name__ == "__main__":
    test_stats = {"runs_per_game": 4.8}
    test_pitcher = {"era": 3.50, "whip": 1.15}
    new_score, factors = project_runs(test_stats, test_pitcher, is_home=True,
                                       weather_adj=1.05, injury_adj=-0.3, line_adj=0.05)
    old_score = _parity_check_old_style(test_stats, test_pitcher, is_home=True,
                                         weather_adj=1.05, injury_adj=-0.3, line_adj=0.05)
    parity_ok = abs(new_score - old_score) < 0.01
    print(f"Parity check: new={new_score:.3f} old={old_score:.3f} -> {'PASS' if parity_ok else 'FAIL — DO NOT SHIP'}")
    print(f"  Factors: {factors}")
    print()

    events = get_mlb_events()
    for event in events:
        pred = predict_game(event)
        print(f"{pred['away_team']} @ {pred['home_team']}")
        print(f"  home_factors: {pred['home_factors']}")
        print(f"  away_factors: {pred['away_factors']}")
        print(pred)