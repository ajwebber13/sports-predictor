"""
routes_mlb.py
FastAPI routes for MLB predictions — mirrors routes_cfb.py / routes_nfl.py.
"""

from fastapi import APIRouter
from mlb_data import get_mlb_events
from mlb_predictor import predict_game

router = APIRouter(prefix="/mlb", tags=["MLB"])


@router.get("/predictions")
def mlb_predictions():
    """
    Returns ALL games with predictions, no edge filter — matches
    the WNBA/CFB/NFL /predictions route used by morning briefings.
    """
    events = get_mlb_events()
    results = []

    for event in events:
        pred = predict_game(event)
        results.append(pred)

    return {"count": len(results), "games": results}


@router.get("/edges")
def mlb_edges(edge_threshold: float = 0.10):
    """
    Returns only games where model probability diverges from
    implied odds probability by >= edge_threshold.
    TODO: wire in odds comparison once Odds API / ESPN odds
    fetch is added to mlb_data.py — right now this returns
    model predictions only, no real edge calc yet.
    """
    events = get_mlb_events()
    results = []

    for event in events:
        pred = predict_game(event)
        # placeholder edge flag until odds comparison is wired in
        pred["has_edge"] = False
        results.append(pred)

    return {"count": len(results), "games": results}


@router.get("/preview")
def mlb_preview():
    """
    Lightweight game list for morning briefing — team names and
    basic matchup info without full prediction payload.
    """
    events = get_mlb_events()
    preview = [
        {"home_team": e["home_team"], "away_team": e["away_team"]}
        for e in events
    ]
    return {"count": len(preview), "games": preview}