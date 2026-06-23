from fastapi import APIRouter, Query
import sys, os

# Resolve project root regardless of working directory
_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/wnba", tags=["WNBA"])


def get_market_implied(events_odds: list, home: str, away: str) -> tuple:
    """
    Returns (home_implied, away_implied) from live odds.
    Falls back to -110 implied (~52.4%) if not found.
    Uses median across bookmakers to avoid bad data.
    """
    from services.odds_parser import american_to_implied
    home_probs = []
    away_probs = []
    for game in events_odds:
        game_home = game.get("home_team", "")
        game_away = game.get("away_team", "")
        if not (home.lower() in game_home.lower() or game_home.lower() in home.lower()):
            continue
        if not (away.lower() in game_away.lower() or game_away.lower() in away.lower()):
            continue
        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market["key"] != "h2h":
                    continue
                for o in market.get("outcomes", []):
                    price = o.get("price", 0)
                    name  = o.get("name", "")
                    if abs(price) > 2000:
                        continue
                    prob = round(american_to_implied(price) * 100, 1)
                    if home.lower() in name.lower():
                        home_probs.append(prob)
                    elif away.lower() in name.lower():
                        away_probs.append(prob)
    default = round(american_to_implied(-110) * 100, 1)
    if not home_probs or not away_probs:
        return default, default
    home_probs.sort()
    away_probs.sort()
    home_implied = home_probs[len(home_probs) // 2]
    away_implied = away_probs[len(away_probs) // 2]
    return home_implied, away_implied


@router.get("/edges")
def wnba_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    from wnba_data            import get_team_stats, TEAM_IDS, get_wnba_events
    from wnba_predictor       import WNBAPredictionEngine
    from services.odds_parser import american_to_implied, get_live_odds

    engine      = WNBAPredictionEngine()
    events      = get_wnba_events()
    events_odds = get_live_odds("wnba")
    results     = []

    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home not in TEAM_IDS or away not in TEAM_IDS:
            continue
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        pred                     = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
        implied_home, implied_away = get_market_implied(events_odds, home, away)
        edge_home                = round(pred.home_win_prob - implied_home, 2)
        edge_away                = round(pred.away_win_prob - implied_away, 2)
        label                    = f"{away} @ {home}"

        if edge_home >= min_edge:
            home_prob_dec = pred.home_win_prob / 100
            home_odds = round(-(home_prob_dec / (1 - home_prob_dec)) * 100) if home_prob_dec >= 0.5 else round(((1 - home_prob_dec) / home_prob_dec) * 100)
            results.append({
                "game": label, "bet": f"{home} ML", "model_prob": pred.home_win_prob,
                "implied_prob": implied_home, "edge": round(edge_home / 100, 4),
                "odds": home_odds,
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            })

        if edge_away >= min_edge:
            away_prob_dec = pred.away_win_prob / 100
            away_odds = round(-(away_prob_dec / (1 - away_prob_dec)) * 100) if away_prob_dec >= 0.5 else round(((1 - away_prob_dec) / away_prob_dec) * 100)
            results.append({
                "game": label, "bet": f"{away} ML", "model_prob": pred.away_win_prob,
                "implied_prob": implied_away, "edge": round(edge_away / 100, 4),
                "odds": away_odds,
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            })

    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}


@router.get("/preview")
def wnba_preview(home: str, away: str, simulations: int = Query(default=10000)):
    from wnba_data      import get_team_stats, get_roster, TEAM_IDS
    from wnba_predictor import WNBAPredictionEngine
    if home not in TEAM_IDS or away not in TEAM_IDS:
        return {"error": f"Unknown team. Available: {list(TEAM_IDS.keys())}"}
    home_stats = get_team_stats(home)
    away_stats = get_team_stats(away)
    if not home_stats or not away_stats:
        return {"error": "Could not fetch team stats from ESPN"}
    engine = WNBAPredictionEngine()
    pred   = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
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


@router.get("/predictions")
def wnba_predictions(simulations: int = Query(default=10000)):
    """Returns model predictions for ALL today's WNBA games, no edge filter."""
    from wnba_data            import get_team_stats, TEAM_IDS, get_wnba_events
    from wnba_predictor       import WNBAPredictionEngine
    from services.odds_parser import american_to_implied, get_live_odds

    engine      = WNBAPredictionEngine()
    events      = get_wnba_events()
    events_odds = get_live_odds("wnba")
    results     = []

    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home not in TEAM_IDS or away not in TEAM_IDS:
            continue
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        pred                       = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
        home_implied, away_implied = get_market_implied(events_odds, home, away)
        e_home                     = round(pred.home_win_prob - home_implied, 2)
        e_away                     = round(pred.away_win_prob - away_implied, 2)
        implied                    = home_implied if e_home >= e_away else away_implied
        best_edge                  = max(e_home, e_away)
        label                      = f"{away} @ {home}"

        bet_prob     = pred.home_win_prob if e_home >= e_away else pred.away_win_prob
        bet_prob_dec = bet_prob / 100
        if bet_prob_dec >= 0.5:
            bet_odds = round(-(bet_prob_dec / (1 - bet_prob_dec)) * 100)
        else:
            bet_odds = round(((1 - bet_prob_dec) / bet_prob_dec) * 100)

        # Use model's predicted winner for bet label
        bet_label = f"{home} ML" if pred.home_win_prob > pred.away_win_prob else f"{away} ML"
        results.append({
            "game":         label,
            "bet":          bet_label,
            "model_prob":   pred.home_win_prob,
            "implied_prob": implied,
            "edge":         round(best_edge / 100, 4),
            "odds":         bet_odds,
            "projected":    f"{pred.projected_home}-{pred.projected_away}",
            "home_record":  pred.home_record,
            "away_record":  pred.away_record,
            "home_rest":    pred.home_rest_days,
            "away_rest":    pred.away_rest_days,
        })

    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}