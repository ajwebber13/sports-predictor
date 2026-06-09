from fastapi import APIRouter, Query
import sys, os
sys.path.insert(0, os.path.abspath("."))
router = APIRouter(prefix="/wnba", tags=["WNBA"])

@router.get("/edges")
def wnba_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    from wnba_data import get_team_stats, TEAM_IDS, get_wnba_events
    from wnba_predictor import WNBAPredictionEngine
    from services.odds_parser import american_to_implied
    engine = WNBAPredictionEngine()
    events = get_wnba_events()
    results = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home not in TEAM_IDS or away not in TEAM_IDS:
            continue
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
        implied_home = round(american_to_implied(-110) * 100, 1)
        implied_away = round(american_to_implied(-110) * 100, 1)
        edge_home = round(pred.home_win_prob - implied_home, 2)
        edge_away = round(pred.away_win_prob - implied_away, 2)
        label = f"{away} @ {home}"
        if edge_home >= min_edge:
            results.append({"game": label, "bet": f"{home} ML", "model_prob": pred.home_win_prob,
                "implied_prob": implied_home, "edge": round(edge_home / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days})
        if edge_away >= min_edge:
            results.append({"game": label, "bet": f"{away} ML", "model_prob": pred.away_win_prob,
                "implied_prob": implied_away, "edge": round(edge_away / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days})
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}

@router.get("/preview")
def wnba_preview(home: str, away: str, simulations: int = Query(default=10000)):
    from wnba_data import get_team_stats, get_roster, TEAM_IDS
    from wnba_predictor import WNBAPredictionEngine
    if home not in TEAM_IDS or away not in TEAM_IDS:
        return {"error": f"Unknown team. Available: {list(TEAM_IDS.keys())}"}
    home_stats = get_team_stats(home)
    away_stats = get_team_stats(away)
    if not home_stats or not away_stats:
        return {"error": "Could not fetch team stats from ESPN"}
    engine = WNBAPredictionEngine()
    pred = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
    home_roster = get_roster(home)
    away_roster = get_roster(away)
    return {
        "prediction": pred.to_dict(),
        "rosters": {
            home: [{"name": p.name, "position": p.position, "status": p.status}
                   for p in (home_roster.players[:10] if home_roster else [])],
            away: [{"name": p.name, "position": p.position, "status": p.status}
                   for p in (away_roster.players[:10] if away_roster else [])],
        },
    }