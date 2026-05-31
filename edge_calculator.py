"""
services/edge_calculator.py
Calculates edges between model probabilities and market-implied probabilities.
"""

from services.odds_parser import get_live_odds, parse_spread, american_to_implied

# Minimum edge threshold to surface a bet
EDGE_THRESHOLD = 0.03  # 3%


def calculate_edge(model_prob: float, odds: int) -> float:
    """
    Edge = model probability - implied probability from market odds.
    Positive edge = model thinks this is underpriced by the market.
    """
    implied = american_to_implied(odds)
    return round(model_prob - implied, 4)


def calculate_ev(edge: float, odds: int) -> float:
    """
    Expected Value = edge * payout ratio.
    Simplified EV as a % of stake.
    """
    if odds > 0:
        payout = odds / 100
    else:
        payout = 100 / abs(odds)
    return round(edge * payout, 4)


def get_edges(sport: str = "ncaaf", model_probs: dict = None) -> list:
    """
    Fetches live odds and compares against model probabilities.

    model_probs: dict keyed by team name -> win probability
    Example: {"LSU": 0.62, "Clemson": 0.38}

    If model_probs is None, uses a flat 0.55 placeholder (replace with real model).
    """
    games = get_live_odds(sport)
    best_bets = []

    for game in games:
        home = game["home_team"]
        away = game["away_team"]
        spreads = parse_spread(game)

        if not spreads:
            continue

        for outcome in spreads:
            team = outcome["name"]
            line = outcome["point"]
            price = outcome["price"]

            # Use real model prob if available, else placeholder
            if model_probs and team in model_probs:
                model_prob = model_probs[team]
            else:
                model_prob = 0.55  # TODO: replace with predictor_core output

            edge = calculate_edge(model_prob, price)
            ev = calculate_ev(edge, price)

            if edge >= EDGE_THRESHOLD:
                best_bets.append({
                    "game": f"{away} @ {home}",
                    "bet": f"{team} {line}",
                    "odds": price,
                    "model_prob": model_prob,
                    "implied_prob": round(american_to_implied(price), 4),
                    "edge": edge,
                    "ev": ev,
                })

    # Sort by highest edge first
    return sorted(best_bets, key=lambda x: x["edge"], reverse=True)
