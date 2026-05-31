from fastapi import APIRouter, Query
from services.model_connector import get_model_edges

router = APIRouter()

@router.get("/")
def edges(
    sport: str = Query(default="ncaaf"),
    simulations: int = Query(default=10000),
):
    results = get_model_edges(sport=sport, simulations=simulations)
    if not results:
        return {"sport": sport, "count": 0, "best_bets": []}
    return {"sport": sport, "count": len(results), "best_bets": results}
