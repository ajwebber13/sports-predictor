"""
prediction_registry.py

Stores every prediction for later
backtesting and model evaluation.
"""

import json
import uuid
from pathlib import Path
from datetime import datetime

PREDICTION_DIR = Path("data/predictions")
PREDICTION_DIR.mkdir(parents=True, exist_ok=True)


def save_prediction(prediction: dict):

    prediction["id"] = str(uuid.uuid4())
    prediction["created_at"] = datetime.utcnow().isoformat()

    filename = (
        f"{prediction['league']}_"
        f"{prediction['game_date']}_"
        f"{prediction['home_team']}_"
        f"{prediction['away_team']}.json"
    )

    path = PREDICTION_DIR / filename

    with open(path, "w") as f:
        json.dump(prediction, f, indent=4)

    return path


def load_predictions():

    predictions = []

    for file in PREDICTION_DIR.glob("*.json"):
        with open(file) as f:
            predictions.append(json.load(f))

    return predictions


def get_prediction(prediction_id):

    for prediction in load_predictions():
        if prediction["id"] == prediction_id:
            return prediction

    return None