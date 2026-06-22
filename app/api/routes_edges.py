from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/")
def edges(
    sport: str = Query(default="ncaaf"),
    simulations: int = Query(default=10000),
):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    sys.path.insert(0, os.path.join(os.path.abspath("."), "services"))
    from services.model_connector import get_model_edges
    results = get_model_edges(sport=sport, simulations=simulations)
    return {"sport": sport, "count": len(results), "best_bets": results}
