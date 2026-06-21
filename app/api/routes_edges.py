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


@router.get("/wnba/edges")
def wnba_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from wnba_data import get_team_stats, TEAM_IDS
    from wnba_predictor import WNBAPredictionEngine
    from wnba_props import get_wnba_events
    from odds_parser import american_to_implied
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
        implied = round(american_to_implied(-110) * 100, 1)
        e_home = round(pred.home_win_prob - implied, 2)
        e_away = round(pred.away_win_prob - implied, 2)
        label = f"{away} @ {home}"
        if e_home >= min_edge:
            results.append({
                "game": label, "bet": f"{home} ML",
                "model_prob": pred.home_win_prob, "implied_prob": implied,
                "edge": round(e_home / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            })
        if e_away >= min_edge:
            results.append({
                "game": label, "bet": f"{away} ML",
                "model_prob": pred.away_win_prob, "implied_prob": implied,
                "edge": round(e_away / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            })
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}


@router.get("/wnba/props")
def wnba_props(min_edge: float = Query(default=3.0)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from wnba_props import get_wnba_prop_edges
    edges = get_wnba_prop_edges(min_edge=min_edge)
    return {"count": len(edges), "props": edges}


@router.get("/wnba/preview")
def wnba_preview(home: str, away: str, simulations: int = Query(default=10000)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from wnba_data import get_team_stats, get_roster, TEAM_IDS
    from wnba_predictor import WNBAPredictionEngine
    if home not in TEAM_IDS or away not in TEAM_IDS:
        return {"error": f"Unknown team. Available: {list(TEAM_IDS.keys())}"}
    home_stats = get_team_stats(home)
    away_stats = get_team_stats(away)
    if not home_stats or not away_stats:
        return {"error": "Could not fetch stats"}
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


@router.get("/wnba/predictions")
def wnba_predictions(simulations: int = Query(default=10000)):
    """Returns model predictions for ALL today's WNBA games — no edge filter."""
    import sys, os
    src = os.path.abspath(".")
    sys.path.insert(0, src)
    sys.path.insert(0, os.path.join(src, "app"))
    sys.path.insert(0, os.path.join(src, "app", "api"))
    from wnba_data      import get_team_stats, TEAM_IDS
    from wnba_predictor import WNBAPredictionEngine
    from wnba_props     import get_wnba_events
    from odds_parser    import american_to_implied

    engine  = WNBAPredictionEngine()
    events  = get_wnba_events()
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

        pred      = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
        implied   = round(american_to_implied(-110) * 100, 1)
        e_home    = round(pred.home_win_prob - implied, 2)
        e_away    = round(pred.away_win_prob - implied, 2)
        best_edge = max(e_home, e_away)
        label     = f"{away} @ {home}"

        results.append({
            "game":         label,
            "bet":          f"{home} ML" if e_home >= e_away else f"{away} ML",
            "model_prob":   pred.home_win_prob,
            "implied_prob": implied,
            "edge":         round(best_edge / 100, 4),
            "projected":    f"{pred.projected_home}-{pred.projected_away}",
            "home_record":  pred.home_record,
            "away_record":  pred.away_record,
            "home_rest":    pred.home_rest_days,
            "away_rest":    pred.away_rest_days,
        })

    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}