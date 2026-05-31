import random

def simulate_game(home_rating: float, away_rating: float, n: int = 5000):
    home_wins = 0

    for _ in range(n):
        home_score = random.gauss(home_rating, 6.5)
        away_score = random.gauss(away_rating, 6.5)

        if home_score > away_score:
            home_wins += 1

    return home_wins / n