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
from database import get_conn, get_situational_row as _get_situational_row, get_line_movement_adj
from intel_feed import get_matchup_injury_adj

MLB_CONSTANTS = {
    "home_adv": 0.35,      # home teams average ~0.35 more runs/game than road teams
    "std_dev": 3.0,         # kept for reference/logging, not used directly in Poisson sim
    "home_win_pct": 0.535,  # baseline to sanity-check model output against
}

SIMS = 10000



def project_runs(team_stats, pitcher_stats, is_home, weather_adj=1.0, situational_adj=0.0, injury_adj=0.0, line_adj=0.0):
    """
    Build a team's projected runs for the game.

    Returns (final_runs, factors) — factors is a named breakdown for
    the prediction_factors explainability log. Unlike WNBA/CFB/NFL,
    this is NOT a pure sum: pitcher quality and weather are real
    multipliers on the base rate (an ace doesn't subtract a fixed
    number of runs, he multiplies your scoring chances down), while
    situational travel and injuries are point adjustments added on
    top. The factors dict keeps multipliers labeled as multipliers
    (pitcher_factor, weather_factor) so nothing gets summed that
    shouldn't be — see the parity check in __main__, which replays
    the actual formula rather than summing the dict.

    injury_adj covers the OTHER 8 lineup spots (a missing everyday
    bat) — the starting pitcher's own quality is already priced in
    via era/whip above, so this deliberately does not double-count
    a starter being hurt.
    """
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

    final = max(base, 0.5)
    return final, factors


def simulate_game(home_runs_proj, away_runs_proj, sims=SIMS, run_line=None, total_line=None):
    """
    run_line: the HOME team's posted run line (e.g. -1.5 if home is
    favored by 1.5, +1.5 if home is the underdog) — same sign
    convention as get_run_line_odds()'s "home_line". None if no real
    line is available (moneyline-only game, same as today's behavior).

    total_line: the posted over/under total. None if unavailable.

    Cover/O-U probabilities are computed from the SAME simulated
    home_scores/away_scores arrays as the win probability — one
    Monte Carlo pass, not a second simulation — mirroring
    wnba_predictor.py's approach (home_cov/away_cov/over_p/under_p
    all derived from one set of simulated scores).
    """
    home_scores = np.random.poisson(lam=home_runs_proj, size=sims)
    away_scores = np.random.poisson(lam=away_runs_proj, size=sims)

    ties = home_scores == away_scores
    while ties.sum() > 0:
        n = ties.sum()
        home_scores[ties] = np.random.poisson(lam=home_runs_proj, size=n)
        away_scores[ties] = np.random.poisson(lam=away_runs_proj, size=n)
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
    }

    # Run line (spread): margin = home - away. Home covers a -1.5 line
    # if margin > 1.5 (i.e. margin + home_line > 0, since home_line is
    # negative when favored — same sign convention as WNBA's spread
    # math: margin > -home_line). Skipped entirely if no real line —
    # never fabricates a number, same principle as the rest of this
    # engine (ranking_engine.py, edge_finder.py, etc.).
    if run_line is not None:
        margin = home_scores - away_scores
        home_cover = np.sum(margin > -run_line) / sims
        away_cover = np.sum(margin < -run_line) / sims
        result["home_cover_prob"] = float(round(home_cover * 100, 1))
        result["away_cover_prob"] = float(round(away_cover * 100, 1))
    else:
        result["home_cover_prob"] = None
        result["away_cover_prob"] = None

    # Total (over/under) — same single simulation pass.
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


def predict_game(event):
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
        # No row for today yet — fall back to the original live ESPN
        # lookup for rest days (display only, matches prior behavior),
        # no situational adjustment applied since none is on record.
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

    home_runs_proj, home_factors = project_runs(home_stats, home_pitcher_stats, is_home=True, weather_adj=weather_adj, injury_adj=home_inj_adj, line_adj=home_line_adj)
    away_runs_proj, away_factors = project_runs(away_stats, away_pitcher_stats, is_home=False, weather_adj=weather_adj, situational_adj=total_adj, injury_adj=away_inj_adj, line_adj=away_line_adj)

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

    result["home_record"] = get_team_record(home_comp)
    result["away_record"] = get_team_record(away_comp)
    result["home_injuries"] = get_team_injuries(home_comp)
    result["away_injuries"] = get_team_injuries(away_comp)
    result["home_rest"] = home_rest
    result["away_rest"] = away_rest

    # Posted lines/odds passed through so routes_mlb.py can compute
    # spread_pick/spread_edge and the total pick without re-fetching.
    result["posted_run_line"] = run_line_odds["home_line"] if run_line_odds else None
    result["run_line_home_odds"] = run_line_odds["home_odds"] if run_line_odds else None
    result["run_line_away_odds"] = run_line_odds["away_odds"] if run_line_odds else None
    result["posted_total"] = total_odds["line"] if total_odds else None
    result["total_over_odds"] = total_odds["over_odds"] if total_odds else None
    result["total_under_odds"] = total_odds["under_odds"] if total_odds else None

    return result


def _parity_check_old_style(team_stats, pitcher_stats, is_home, weather_adj=1.0,
                             situational_adj=0.0, injury_adj=0.0, line_adj=0.0):
    """Reference implementation — exact pre-refactor math, parity check only."""
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
    # Parity check on synthetic inputs — doesn't need a live event
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
        print(pred)