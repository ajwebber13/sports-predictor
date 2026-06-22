from fastapi import APIRouter
from services.slate_builder import get_slate
from model.inference.predictor import predict_game

router = APIRouter()

@router.get("/")
def slate():
    slate = get_slate()

    results = []
    for g in slate:
        pred = predict_game(g["home"], g["away"])

        results.append({
            "home": g["home"],
            "away": g["away"],
            "home_win_prob": pred["home_win_prob"],
            "away_win_prob": pred["away_win_prob"],
            "confidence": pred["confidence"]
        })

    return {"games": results}