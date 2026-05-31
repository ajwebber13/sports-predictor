def implied_prob(odds: float):
    return 1 / odds


def calculate_edge(model_prob: float, odds: float):
    return model_prob - implied_prob(odds)