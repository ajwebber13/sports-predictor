"""
predictor.py
=============
Core constants and utility functions used by enhanced_predictor.py
"""

# ─────────────────────────────────────────────────────────────
# LEAGUE CONSTANTS
# ─────────────────────────────────────────────────────────────

CFB_CONSTANTS = {
    "league_avg_pts":      29.0,
    "league_avg_ypp":       5.9,
    "league_avg_to_given":  1.5,
    "home_adv_pts":         3.0,
    "score_std_dev":       10.5,
}

NFL_CONSTANTS = {
    "league_avg_pts":      23.0,
    "league_avg_ypp":       5.6,
    "league_avg_to_given":  1.2,
    "home_adv_pts":         2.5,
    "score_std_dev":        9.5,
}

WNBA_CONSTANTS = {
    "league_avg_pts":      82.0,
    "league_avg_ypp":       1.00,
    "league_avg_to_given": 13.5,
    "home_adv_pts":         3.0,
    "score_std_dev":       10.0,
}

NBA_CONSTANTS = {
    "league_avg_pts":     113.0,
    "league_avg_ypp":       5.65,
    "league_avg_to_given": 13.5,
    "home_adv_pts":         3.0,
    "score_std_dev":       11.0,
}


# ─────────────────────────────────────────────────────────────
# ODDS UTILITIES
# ─────────────────────────────────────────────────────────────

def american_to_implied(odds: int) -> float:
    """Convert American odds to implied probability (0-1 scale)."""
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def remove_vig(prob_a: float, prob_b: float):
    """Remove vig from two implied probabilities."""
    total = prob_a + prob_b
    if total == 0:
        return 0.5, 0.5
    return round(prob_a / total * 100, 1), round(prob_b / total * 100, 1)
