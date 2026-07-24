import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from odds_parser import get_live_odds, american_to_implied
from enhanced_predictor import EnhancedPredictionEngine
from enhanced_data import GameContext

try:
    from data.team_profiles import TEAM_PROFILES
except ImportError:
    TEAM_PROFILES = {}

try:
    from data.nfl_profiles import NFL_PROFILES
except ImportError:
    NFL_PROFILES = {}

try:
    from data.wnba_profiles import WNBA_PROFILES
except ImportError:
    WNBA_PROFILES = {}

try:
    from data.nba_profiles import NBA_PROFILES
except ImportError:
    NBA_PROFILES = {}

ALL_PROFILES = {**TEAM_PROFILES, **NFL_PROFILES, **WNBA_PROFILES, **NBA_PROFILES}

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

# Standard deviation of final score margin per sport, used by
# spread_to_moneyline()'s normal-distribution approximation. These are
# published sports-analytics approximations (public literature), NOT
# fit against Drew's own historical picks — a real fit needs his own
# graded spread-conversion history, which doesn't exist yet. Still a
# materially better default than one flat coefficient applied to
# every sport identically (see spread_to_moneyline()'s docstring).
SPREAD_SIGMA = {
    "nfl": 13.5,
    "ncaaf": 16.5,   # CFB has meaningfully higher game-margin variance than NFL — blowouts are routine
    "nba": 12.0,
    "ncaab": 11.0,
    "wnba": 10.5,
}
DEFAULT_SPREAD_SIGMA = 14.0  # fallback for an unrecognized sport key


def normalize_name(name):
    return NAME_MAP.get(name, name)


def no_vig_implied(odds_home, odds_away):
    """Converts a real h2h price pair into NO-VIG (fair) probabilities,
    renormalized to sum to 100%. Real market odds sum to ~104-106% (the
    vig); comparing model_prob against the raw un-normalized number
    overstates the bookmaker's cut as if it were part of your real edge.
    """
    raw_home = american_to_implied(odds_home) * 100
    raw_away = american_to_implied(odds_away) * 100
    total = raw_home + raw_away
    i_home = round(raw_home / total * 100, 1)
    i_away = round(raw_away / total * 100, 1)
    return i_home, i_away


def nba_win_prob(home_profile, away_profile) -> float:
    """
    NBA win probability based on net rating differential.
    Bypasses football rating engine — uses pts scored/allowed directly.
    """
    home_net = home_profile.pts_off - home_profile.pts_def
    away_net = away_profile.pts_off - away_profile.pts_def
    diff = (home_net - away_net) + 3.0  # home court advantage
    prob = 1 / (1 + math.exp(-diff / 8.0))
    return round(prob * 100, 1)


def wnba_win_prob(home_profile, away_profile) -> float:
    """
    WNBA win probability based on net points differential.
    """
    home_net = home_profile.pts_off - home_profile.pts_def
    away_net = away_profile.pts_off - away_profile.pts_def
    diff = (home_net - away_net) + 3.0
    prob = 1 / (1 + math.exp(-diff / 8.0))
    return round(prob * 100, 1)


def get_model_edges(sport="ncaaf", context=None, simulations=10000):
    games = get_live_odds(sport)
    results = []

    for game in games:
        home = normalize_name(game.get("home_team", ""))
        away = normalize_name(game.get("away_team", ""))

        if home not in ALL_PROFILES or away not in ALL_PROFILES:
            continue

        spread_line, over_under, odds_home, odds_away = _extract_lines(game, sport)
        label = f"{away} @ {home}"
        i_home, i_away = no_vig_implied(odds_home, odds_away)

        # ── NBA: use net rating model ──────────────────────────
        if sport == "nba":
            m_home = nba_win_prob(ALL_PROFILES[home], ALL_PROFILES[away])
            m_away = round(100 - m_home, 1)
            e_home = round(m_home - i_home, 2)
            e_away = round(m_away - i_away, 2)
            home_net = round(ALL_PROFILES[home].pts_off - ALL_PROFILES[home].pts_def, 1)
            away_net = round(ALL_PROFILES[away].pts_off - ALL_PROFILES[away].pts_def, 1)
            if e_home >= EDGE_THRESHOLD:
                results.append({"game": label, "bet": f"{home} ML", "odds": odds_home,
                    "model_prob": m_home, "implied_prob": i_home, "edge": e_home / 100,
                    "cover_prob": "N/A", "confidence": "NBA Net Rating Model",
                    "net_rating_home": home_net, "net_rating_away": away_net})
            if e_away >= EDGE_THRESHOLD:
                results.append({"game": label, "bet": f"{away} ML", "odds": odds_away,
                    "model_prob": m_away, "implied_prob": i_away, "edge": e_away / 100,
                    "cover_prob": "N/A", "confidence": "NBA Net Rating Model",
                    "net_rating_home": home_net, "net_rating_away": away_net})
            continue

        # ── Full EnhancedPredictionEngine for football ─────────
        try:
            prediction = engine.predict(
                profile_a=ALL_PROFILES[home], profile_b=ALL_PROFILES[away],
                spread_line=spread_line, over_under=over_under,
                odds_a=odds_home, odds_b=odds_away,
                neutral_site=False, a_is_home=True,
                context=context or GameContext(), simulations=simulations,
            )
            m_home = prediction.team_a_win_prob
            m_away = prediction.team_b_win_prob
            e_home = round(m_home - i_home, 2)
            e_away = round(m_away - i_away, 2)

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
        except Exception as e:
            print(f"get_model_edges: prediction error for {label}: {e}")
            continue

    return sorted(results, key=lambda x: x["edge"], reverse=True)


def _extract_lines(game, sport="ncaaf"):
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

    if odds_home == -110 and odds_away == -110 and spread_line != 0.0:
        odds_home, odds_away = spread_to_moneyline(spread_line, sport)

    return spread_line, over_under, odds_home, odds_away


def _normal_cdf(x: float) -> float:
    """Standard normal CDF via math.erf — no scipy dependency needed."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def spread_to_moneyline(spread: float, sport: str = "ncaaf"):
    """
    Converts a posted point spread into an implied win probability
    using a normal-distribution approximation of final score margin —
    P(win) = Phi(favored_margin / sigma), standard sports-analytics
    practice. sigma is the standard deviation of final margin for the
    given sport (see SPREAD_SIGMA above).

    FIXED 2026-07-24: this function previously used one flat logistic
    curve (1 / (1 + exp(spread * 0.15))) for every sport that calls
    it, and didn't even accept a sport argument to distinguish them.
    Verified against real published NFL win-rate-by-spread tables, the
    old flat formula was reasonably close for NFL specifically (~61%
    at -3, ~74% at -7, ~82% at -10, vs commonly cited real rates of
    roughly 58-62%/68-72%/76-80%) but meaningfully overconfident once
    applied to CFB, whose real game-margin variance is much higher —
    at a -14 CFB spread the old formula implied ~89% win probability
    vs a more realistic ~80% once CFB's own variance is used; at -21
    it was 96% vs ~90%. This overconfidence in the fallback synthetic
    price (used only when no real h2h odds exist) runs in the same
    direction as the broader confidence-overconfidence pattern already
    found in calibration_audit.py, though it's a separate mechanism.

    SPREAD_SIGMA values are published sports-analytics approximations,
    not fit against Drew's own historical picks (no such fit data
    exists yet) — a real improvement, not a final tuned answer.
    """
    sigma = SPREAD_SIGMA.get(sport, DEFAULT_SPREAD_SIGMA)
    home_win_prob = _normal_cdf(-spread / sigma)
    away_win_prob = 1 - home_win_prob

    def prob_to_american(p):
        p = max(0.01, min(0.99, p))
        if p >= 0.5:
            return round(-(p / (1 - p)) * 100)
        else:
            return round(((1 - p) / p) * 100)

    return prob_to_american(home_win_prob), prob_to_american(away_win_prob)
