from model.inference.simulator import simulate_game

# simple baseline ratings (you'll replace later with real data)
TEAM_RATINGS = {
    "LSU": 29,
    "Clemson": 27,
    "Alabama": 31,
    "Georgia": 30,
    "Texas": 28,
    "Oklahoma": 27
}

def predict_game(home: str, away: str, neutral_site: bool = False):

    home_rating = TEAM_RATINGS.get(home, 26)
    away_rating = TEAM_RATINGS.get(away, 26)

    if neutral_site:
        home_rating -= 1

    home_win_prob = simulate_game(home_rating, away_rating)
    away_win_prob = 1 - home_win_prob

    # simple projected score proxy
    home_score = home_rating
    away_score = away_rating

    confidence = abs(home_win_prob - 0.5) * 2

    return {
        "home_win_prob": round(home_win_prob, 4),
        "away_win_prob": round(away_win_prob, 4),
        "home_score": home_score,
        "away_score": away_score,
        "confidence": round(confidence, 4)
    }