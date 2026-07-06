"""
routes_mlb.py
FastAPI routes for MLB predictions — mirrors routes_cfb.py / routes_nfl.py.
"""

from fastapi import APIRouter
from mlb_data import get_mlb_events, get_moneyline_odds, american_to_implied
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
def mlb_edges(min_edge: float = 3.0):
    """
    Returns games where model probability diverges from DraftKings
    implied probability by >= min_edge (percentage points).
    """
    events = get_mlb_events()
    results = []

    for event in events:
        pred = predict_game(event)
        odds = get_moneyline_odds(event)

        if not odds:
            pred["has_edge"] = False
            results.append(pred)
            continue

        implied_home = round(american_to_implied(odds["home"]) * 100, 1)
        implied_away = round(american_to_implied(odds["away"]) * 100, 1)

        model_home = round(pred["home_win_prob"] * 100, 1)
        model_away = round(pred["away_win_prob"] * 100, 1)

        edge_home = round(model_home - implied_home, 2)
        edge_away = round(model_away - implied_away, 2)

        pred["implied_home_prob"] = implied_home
        pred["implied_away_prob"] = implied_away
        pred["edge_home"] = edge_home
        pred["edge_away"] = edge_away
        pred["has_edge"] = edge_home >= min_edge or edge_away >= min_edge

        results.append(pred)

    edge_games = [g for g in results if g["has_edge"]]
    return {"count": len(edge_games), "games": edge_games}


@router.get("/preview")
def mlb_preview():
    """
    Lightweight game list for morning briefing — team names and
    basic matchup info without full prediction payload.
    """
    events = get_mlb_events()
    preview = []
    for e in events:
        competitors = e["competitions"][0]["competitors"]
        home = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "home")
        away = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "away")
        preview.append({"home_team": home, "away_team": away})
    return {"count": len(preview), "games": preview}