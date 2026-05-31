from fastapi import APIRouter
from app.schemas.game import GameRequest
from model.inference.predictor import predict_game

router = APIRouter()

@router.post("/")
def predict(game: GameRequest):
    return predict_game(game.home, game.away, game.neutral_site)