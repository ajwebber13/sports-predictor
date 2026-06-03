import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from odds_parser import get_live_odds, american_to_implied
from enhanced_predictor import EnhancedPredictionEngine
from enhanced_data import GameContext

try:
    from data.team_profiles import TEAM_PROFILES
except ImportError:
    TEAM_PROFILES = {}

NAME_MAP = {
    "LSU Tigers": "LSU", "Clemson Tigers": "Clemson",
    "Alabama Crimson Tide": "Alabama", "Georgia Bulldogs": "Georgia",
    "Ohio State Buckeyes": "Ohio State", "Michigan Wolverines": "Michigan",
    "Texas Longhorns": "Texas", "Oklahoma Sooners": "Oklahoma",
    "Notre Dame Fighting Irish": "Notre Dame",
    "Penn State Nittany Lions": "Penn State", "Oregon Ducks": "Oregon",
}

EDGE_THRESHOLD = 3.0
engine = EnhancedPredictionEngine()

def normalize_name(name):
    return NAME_MAP.get(name, name)

def get_model_edges(sport="ncaaf", context=None, simulations=10000):
    games = get_live_odds(sport)
    results = []
    for game in games:
        home = normalize_name(game.get("home_team", ""))
        away = normalize_name(game.get("away_team", ""))
        if home not in TEAM_PROFILES or away not in TEAM_PROFILES:
            continue
        spread_line, over_under, odds_home, odds_away = _extract_lines(game)
        try:
            prediction = engine.predict(
                profile_a=TEAM_PROFILES[home], profile_b=TEAM_PROFILES[away],
                spread_line=spread_line, over_under=over_under,
                odds_a=odds_home, odds_b=odds_away,
                neutral_site=False, a_is_home=True,
                context=context or GameContext(), simulations=simulations,
            )
            m_home = prediction.team_a_win_prob
            m_away = prediction.team_b_win_prob
            i_home = round(american_to_implied(odds_home) * 100, 1)
            i_away = round(american_to_implied(odds_away) * 100, 1)
            e_home = round(m_home - i_home, 2)
            e_away = round(m_away - i_away, 2)
            label = f"{away} @ {home}"
            if e_home >= EDGE_THRESHOLD:
                results.append({"game": label, "bet": f"{home} ML", "odds": odds_home,
                    "model_prob": round(m_home, 1), "implied_prob": i_home, "edge": e_home / 100,
                    "cover_prob": prediction.team_a_cover_prob,
                    "confidence": prediction.confidence.label() if prediction.confidence else "N/A",
                    "epa_off": round(prediction.epa_off_a, 3), "epa_def": round(prediction.epa_def_a, 3)})
            if e_away >= EDGE_THRESHOLD:
                results.append({"game": label, "bet": f"{away} ML", "odds": odds_away,
                    "model_prob": round(m_away, 1), "implied_prob": i_away, "edge": e_away / 100,
                    "cover_prob": prediction.team_b_cover_prob,
                    "confidence": prediction.confidence.label() if prediction.confidence else "N/A",
                    "epa_off": round(prediction.epa_off_b, 3), "epa_def": round(prediction.epa_def_b, 3)})
        except:
            continue
    return sorted(results, key=lambda x: x["edge"], reverse=True)

def _extract_lines(game):
    spread_line, over_under, odds_home, odds_away = 0.0, 45.0, -110, -110
    for bm in game.get("bookmakers", []):
        for m in bm.get("markets", []):
            if m["key"] == "spreads":
                for o in m["outcomes"]:
                    if o["name"] == game["home_team"]: spread_line = o.get("point", 0.0)
            if m["key"] == "totals":
                for o in m["outcomes"]:
                    if o["name"] == "Over": over_under = o.get("point", 45.0)
            if m["key"] == "h2h":
                for o in m["outcomes"]:
                    if o["name"] == game["home_team"]: odds_home = o["price"]
                    elif o["name"] == game["away_team"]: odds_away = o["price"]

    # If no h2h odds, estimate moneyline from spread
    if odds_home == -110 and odds_away == -110 and spread_line != 0.0:
        odds_home, odds_away = spread_to_moneyline(spread_line)

    return spread_line, over_under, odds_home, odds_away


def spread_to_moneyline(spread: float):
    """
    Estimate moneyline odds from point spread.
    Uses standard NFL/CFB conversion table.
    Negative spread = favorite (home team).
    """
    import math
    # Win probability from spread using logistic function
    # Each point of spread ~ 3% win probability
    home_win_prob = 1 / (1 + math.exp(spread * 0.15))
    away_win_prob = 1 - home_win_prob

    # Convert probability to American odds
    def prob_to_american(p):
        p = max(0.01, min(0.99, p))
        if p >= 0.5:
            return round(-(p / (1 - p)) * 100)
        else:
            return round(((1 - p) / p) * 100)

    return prob_to_american(home_win_prob), prob_to_american(away_win_prob)