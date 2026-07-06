"""
mlb_predictor.py
Live MLB prediction engine — mirrors cfb_predictor.py / nfl_predictor.py structure,
with Poisson-based scoring instead of normal distribution (baseball scores are
low, discrete, and can't go negative — normal distribution breaks down here).
"""

import numpy as np
from mlb_data import (
    get_mlb_events, get_team_stats, get_starting_pitcher, get_pitcher_stats,
    get_team_record, get_team_injuries, get_team_rest_days,
)
from mlb_weather import get_stadium_weather, get_weather_adj

MLB_CONSTANTS = {
    "home_adv": 0.35,      # home teams average ~0.35 more runs/game than road teams
    "std_dev": 3.0,         # kept for reference/logging, not used directly in Poisson sim
    "home_win_pct": 0.535,  # baseline to sanity-check model output against
}

SIMS = 10000


def project_runs(team_stats, pitcher_stats, is_home, weather_adj=1.0):
    """
    Build a team's projected runs for the game.
    Base runs_per_game, adjusted for home/away split, opposing pitcher
    quality (ERA + WHIP blend), and stadium weather.
    """
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

    return max(base, 0.5)


def simulate_game(home_runs_proj, away_runs_proj, sims=SIMS):
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

    return {
        "home_win_prob": float(round(win_prob, 4)),
        "away_win_prob": float(round(1 - win_prob, 4)),
        "proj_home_runs": float(round(avg_home_score, 1)),
        "proj_away_runs": float(round(avg_away_score, 1)),
    }


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

    home_runs_proj = project_runs(home_stats, home_pitcher_stats, is_home=True, weather_adj=weather_adj)
    away_runs_proj = project_runs(away_stats, away_pitcher_stats, is_home=False, weather_adj=weather_adj)

    result = simulate_game(home_runs_proj, away_runs_proj)
    result["home_team"] = home_team
    result["away_team"] = away_team
    result["weather"] = weather.get("conditions", "unknown")

    result["home_record"] = get_team_record(home_comp)
    result["away_record"] = get_team_record(away_comp)
    result["home_injuries"] = get_team_injuries(home_comp)
    result["away_injuries"] = get_team_injuries(away_comp)
    result["home_rest"] = get_team_rest_days(home_id)
    result["away_rest"] = get_team_rest_days(away_id)

    return result


if __name__ == "__main__":
    events = get_mlb_events()
    for event in events:
        pred = predict_game(event)
        print(pred)