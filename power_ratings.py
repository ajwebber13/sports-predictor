"""
Universal team power ratings
"""

from dataclasses import dataclass


@dataclass
class TeamMetrics:

    offense: float
    defense: float
    recent_form: float
    sos: float
    injuries: float


def calculate_power_rating(metrics: TeamMetrics):

    rating = (
        metrics.offense * 0.35 +
        metrics.defense * 0.35 +
        metrics.recent_form * 0.15 +
        metrics.sos * 0.10 +
        metrics.injuries * 0.05
    )

    return round(rating, 2)


def matchup_edge(home_rating, away_rating):

    diff = home_rating - away_rating

    probability = 50 + (diff * 1.5)

    probability = max(1, min(probability, 99))

    return round(probability, 1)