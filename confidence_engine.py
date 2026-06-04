"""
Confidence scoring engine.
"""


def calculate_confidence(
        win_probability,
        edge,
        injury_factor,
        recent_form):

    score = 0

    score += edge * 3
    score += recent_form * 2
    score += injury_factor

    score += abs(win_probability - 50)

    score = min(score, 100)

    if score >= 85:
        tier = "ELITE"

    elif score >= 75:
        tier = "HIGH"

    elif score >= 60:
        tier = "MEDIUM"

    else:
        tier = "LOW"

    return {
        "score": round(score, 1),
        "tier": tier
    }