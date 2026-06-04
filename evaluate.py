import json
import os

def evaluate_all(folder):
    total = 0
    correct_count = 0

    for file in os.listdir(folder):
        if file.endswith(".json"):
            path = os.path.join(folder, file)

            with open(path, "r") as f:
                data = json.load(f)

            predicted = data["prediction"]["predicted_winner"]
            actual = data["actual_result"]["actual_winner"]

            total += 1

            if predicted == actual:
                correct_count += 1

            print(f"{data['game']} | Pred: {predicted} | Actual: {actual}")

    accuracy = correct_count / total if total > 0 else 0

    print("\n--- SUMMARY ---")
    print("Total Games:", total)
    print("Correct:", correct_count)
    print("Accuracy:", round(accuracy * 100, 2), "%")


evaluate_all("data/predictions")