"""
app/api/routes_edges.py
========================
/edges endpoint — now powered by EnhancedPredictionEngine.
Returns real model edges, not placeholder probabilities.
"""

from fastapi import APIRouter, Query
from services.model_connector import get_model_edges

router = APIRouter()


@router.get("/edges")
def edges(
    sport: str = Query(default="ncaaf", description="Sport key: nfl, ncaaf, nba, ncaab"),
    simulations: int = Query(default=10000, description="Monte Carlo simulation count"),
):
    """
    Returns best bets sorted by edge.
    Edge = EnhancedPredictionEngine win prob - market implied prob.
    Only returns edges above 3% threshold.
    """
    results = get_model_edges(sport=sport, simulations=simulations)

    if not results:
        return {
            "sport": sport,
            "count": 0,
            "message": "No edges above threshold, or team profiles not loaded.",
            "best_bets": [],
        }

    return {
        "sport":     sport,
        "count":     len(results),
        "best_bets": results,
    }
