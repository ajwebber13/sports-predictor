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
    Matches the best_bets schema used by NBA/NFL/CFB/NCAAB routes
    so it plugs into render_job.py and telegram_alerts.py unchanged.
    """
    events = get_mlb_events()
    best_bets = []

    for event in events:
        pred = predict_game(event)
        odds = get_moneyline_odds(event)

        if not odds:
            continue

        implied_home = round(american_to_implied(odds["home"]) * 100, 1)
        implied_away = round(american_to_implied(odds["away"]) * 100, 1)

        model_home = round(pred["home_win_prob"] * 100, 1)
        model_away = round(pred["away_win_prob"] * 100, 1)

        edge_home = round(model_home - implied_home, 2)
        edge_away = round(model_away - implied_away, 2)

        game_label = f"{pred['away_team']} @ {pred['home_team']}"
        projected = f"{pred['proj_home_runs']}-{pred['proj_away_runs']}"

        if edge_home >= min_edge:
            best_bets.append({
                "game": game_label,
                "bet": f"{pred['home_team']} ML",
                "odds": odds["home"],
                "model_prob": model_home,
                "implied_prob": implied_home,
                "edge": round(edge_home / 100, 4),
                "projected": projected,
                "home_record": pred.get("home_record", ""),
                "away_record": pred.get("away_record", ""),
                "home_injuries": pred.get("home_injuries", ""),
                "away_injuries": pred.get("away_injuries", ""),
                "home_rest": pred.get("home_rest"),
                "away_rest": pred.get("away_rest"),
            })

        if edge_away >= min_edge:
            best_bets.append({
                "game": game_label,
                "bet": f"{pred['away_team']} ML",
                "odds": odds["away"],
                "model_prob": model_home,
                "implied_prob": implied_home,
                "edge": round(edge_away / 100, 4),
                "projected": projected,
                "home_record": pred.get("home_record", ""),
                "away_record": pred.get("away_record", ""),
                "home_injuries": pred.get("home_injuries", ""),
                "away_injuries": pred.get("away_injuries", ""),
                "home_rest": pred.get("home_rest"),
                "away_rest": pred.get("away_rest"),
            })

    best_bets.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(best_bets), "best_bets": best_bets}


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