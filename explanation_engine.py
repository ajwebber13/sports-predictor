"""
Human-readable prediction explanations.
"""


def generate_explanation(prediction):

    reasons = []

    if prediction["power_edge"] > 5:
        reasons.append(
            "holds a significant power rating advantage"
        )

    if prediction["recent_form_edge"] > 3:
        reasons.append(
            "has been performing better recently"
        )

    if prediction["home_field"]:
        reasons.append(
            "benefits from home-field advantage"
        )

    if prediction["injury_edge"] > 0:
        reasons.append(
            "has fewer injury concerns"
        )

    if not reasons:
        reasons.append(
            "shows a slight statistical advantage"
        )

    team = prediction["predicted_winner"]

    summary = (
        f"{team} is favored because it "
        + ", ".join(reasons)
        + "."
    )

    return summary