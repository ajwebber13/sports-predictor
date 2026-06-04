"""
Evaluate historical predictions.
"""

from prediction_registry import load_predictions


def run_backtest():

    predictions = load_predictions()

    wins = 0
    losses = 0

    for prediction in predictions:

        actual = prediction.get("actual_winner")

        if not actual:
            continue

        if actual == prediction["predicted_winner"]:
            wins += 1
        else:
            losses += 1

    total = wins + losses

    if total == 0:
        return {
            "wins": 0,
            "losses": 0,
            "accuracy": 0
        }

    accuracy = round(
        wins / total * 100,
        2
    )

    return {
        "wins": wins,
        "losses": losses,
        "accuracy": accuracy
    }


if __name__ == "__main__":

    results = run_backtest()

    print("\nMODEL PERFORMANCE")
    print("------------------")
    print(f"Wins: {results['wins']}")
    print(f"Losses: {results['losses']}")
    print(f"Accuracy: {results['accuracy']}%")