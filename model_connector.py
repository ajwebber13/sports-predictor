"""
services/model_connector.py
============================
Bridges EnhancedPredictionEngine with live odds from The Odds API.

Flow:
  1. Fetch live games from odds_parser
  2. Look up EnhancedProfile for each team
  3. Run EnhancedPredictionEngine.predict()
  4. Extract real win probabilities
  5. Calculate true edge vs market implied odds

Usage:
  from services.model_connector import get_model_edges
  results = get_model_edges(sport="ncaaf")
"""

from typing import Optional
from services.odds_parser import get_live_odds, american_to_implied
from enhanced_predictor import EnhancedPredictionEngine, EnhancedPrediction
from enhanced_data import EnhancedProfile, GameContext


# ─────────────────────────────────────────────────────────────
# TEAM PROFILE REGISTRY
# ─────────────────────────────────────────────────────────────
# Import your team profiles here.
# Replace this with however you currently store/load team data.
# Example: from data.team_profiles import TEAM_PROFILES
#
# TEAM_PROFILES should be a dict:
#   { "LSU": EnhancedProfile(...), "Clemson": EnhancedProfile(...), ... }
#
# If you load from a file or database, swap this import out.

try:
    from data.team_profiles import TEAM_PROFILES
except ImportError:
    TEAM_PROFILES = {}  # fallback — add profiles manually below


# ─────────────────────────────────────────────────────────────
# NAME NORMALIZATION
# ─────────────────────────────────────────────────────────────
# The Odds API uses full team names (e.g. "LSU Tigers").
# Your profiles may use short names (e.g. "LSU").
# Add mappings here as needed.

NAME_MAP = {
    "LSU Tigers":             "LSU",
    "Clemson Tigers":         "Clemson",
    "Alabama Crimson Tide":   "Alabama",
    "Georgia Bulldogs":       "Georgia",
    "Ohio State Buckeyes":    "Ohio State",
    "Michigan Wolverines":    "Michigan",
    "Texas Longhorns":        "Texas",
    "Oklahoma Sooners":       "Oklahoma",
    "Notre Dame Fighting Irish": "Notre Dame",
    # Add more as needed
}

def normalize_name(name: str) -> str:
    return NAME_MAP.get(name, name)


# ─────────────────────────────────────────────────────────────
# EDGE THRESHOLD
# ─────────────────────────────────────────────────────────────
EDGE_THRESHOLD = 3.0  # percentage points (model uses 0-100 scale)


# ─────────────────────────────────────────────────────────────
# MAIN CONNECTOR
# ─────────────────────────────────────────────────────────────

engine = EnhancedPredictionEngine()


def get_model_edges(
    sport: str = "ncaaf",
    context: Optional[GameContext] = None,
    simulations: int = 10000,
) -> list:
    """
    Fetches live odds, runs EnhancedPredictionEngine for each game,
    and returns edges where model prob exceeds market implied prob.

    Returns list of edge dicts sorted by edge descending.
    """
    games = get_live_odds(sport)
    results = []

    for game in games:
        home_raw = game.get("home_team", "")
        away_raw = game.get("away_team", "")
        home = normalize_name(home_raw)
        away = normalize_name(away_raw)

        # Skip if we don't have profiles for both teams
        if home not in TEAM_PROFILES or away not in TEAM_PROFILES:
            results.append(_missing_profile_entry(away_raw, home_raw, game))
            continue

        profile_home = TEAM_PROFILES[home]
        profile_away = TEAM_PROFILES[away]

        # Get spread + total from odds
        spread_line, over_under, odds_home, odds_away = _extract_lines(game)

        if odds_home is None or odds_away is None:
            continue

        try:
            prediction: EnhancedPrediction = engine.predict(
                profile_a    = profile_home,
                profile_b    = profile_away,
                spread_line  = spread_line,
                over_under   = over_under,
                odds_a       = odds_home,
                odds_b       = odds_away,
                neutral_site = False,
                a_is_home    = True,
                context      = context or GameContext(),
                simulations  = simulations,
            )

            # Model win probs (0-100 scale from EnhancedPrediction)
            model_prob_home = prediction.team_a_win_prob
            model_prob_away = prediction.team_b_win_prob

            # Market implied probs (0-100 scale)
            implied_home = american_to_implied(odds_home) * 100
            implied_away = american_to_implied(odds_away) * 100

            edge_home = round(model_prob_home - implied_home, 2)
            edge_away = round(model_prob_away - implied_away, 2)

            game_label = f"{away} @ {home}"

            # Add home team edge if above threshold
            if edge_home >= EDGE_THRESHOLD:
                results.append({
                    "game":         game_label,
                    "bet":          f"{home} ML",
                    "odds":         odds_home,
                    "model_prob":   round(model_prob_home, 1),
                    "implied_prob": round(implied_home, 1),
                    "edge":         edge_home,
                    "spread_line":  spread_line,
                    "cover_prob":   prediction.team_a_cover_prob,
                    "confidence":   prediction.confidence.label() if prediction.confidence else "N/A",
                    "epa_off":      prediction.epa_off_a,
                    "epa_def":      prediction.epa_def_a,
                })

            # Add away team edge if above threshold
            if edge_away >= EDGE_THRESHOLD:
                results.append({
                    "game":         game_label,
                    "bet":          f"{away} ML",
                    "odds":         odds_away,
                    "model_prob":   round(model_prob_away, 1),
                    "implied_prob": round(implied_away, 1),
                    "edge":         edge_away,
                    "spread_line":  spread_line,
                    "cover_prob":   prediction.team_b_cover_prob,
                    "confidence":   prediction.confidence.label() if prediction.confidence else "N/A",
                    "epa_off":      prediction.epa_off_b,
                    "epa_def":      prediction.epa_def_b,
                })

        except Exception as e:
            results.append({
                "game":  f"{away} @ {home}",
                "error": str(e),
            })

    return sorted(
        [r for r in results if "error" not in r and "missing_profile" not in r],
        key=lambda x: x["edge"],
        reverse=True
    )


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _extract_lines(game: dict):
    """Extract spread line, over/under, and ML odds from a game object."""
    spread_line = 0.0
    over_under  = 45.0
    odds_home   = None
    odds_away   = None

    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "spreads":
                for outcome in market["outcomes"]:
                    if outcome["name"] == game["home_team"]:
                        spread_line = outcome.get("point", 0.0)
            if market["key"] == "totals":
                for outcome in market["outcomes"]:
                    if outcome["name"] == "Over":
                        over_under = outcome.get("point", 45.0)
            if market["key"] == "h2h":
                for outcome in market["outcomes"]:
                    if outcome["name"] == game["home_team"]:
                        odds_home = outcome["price"]
                    elif outcome["name"] == game["away_team"]:
                        odds_away = outcome["price"]

    # Fallback: if no h2h odds, estimate from spread
    if odds_home is None:
        odds_home = -110
    if odds_away is None:
        odds_away = -110

    return spread_line, over_under, odds_home, odds_away


def _missing_profile_entry(away: str, home: str, game: dict) -> dict:
    """Placeholder for games where team profiles aren't loaded yet."""
    return {
        "missing_profile": True,
        "game": f"{away} @ {home}",
        "note": "Add EnhancedProfile for both teams to get real edge calculation",
    }
