from pydantic import BaseModel

class PredictionResponse(BaseModel):
    home_win_prob: float
    away_win_prob: float
    home_score: float
    away_score: float
    confidence: float