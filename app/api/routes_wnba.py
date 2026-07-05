from fastapi import APIRouter, Query
import sys
import os

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/wnba", tags=["WNBA"])


def get_market_implied(events_odds: list, home: str, away: str) -> tuple:
    from services.odds_parser import american_to_implied
    home_probs = []
    away_probs = []
    for game in events_odds:
        game_home = (game.get("home_team") or "").lower()
        game_away = (game.get("away_team") or "").lower()
        if home.lower() not in game_home and game_home not in home.lower():
            continue
        if away.lower() not in game_away and game_away not in away.lower():
            continue
        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for o in market.get("outcomes", []):
                    price = o.get("price", 0)
                    name = (o.get("name") or "").lower()
                    if abs(price) > 2000:
                        continue
                    prob = round(american_to_implied(price) * 100, 1)
                    if home.lower() in name:
                        home_probs.append(prob)
                    elif away.lower() in name:
                        away_probs.append(prob)
    default = round(american_to_implied(-110) * 100, 1)
    if not home_probs or not away_probs:
        return default, default
    home_probs.sort()
    away_probs.sort()
    return (home_probs[len(home_probs) // 2], away_probs[len(away_probs) // 2])


def _get_spread_and_total(events_odds: list, home: str, away: str) -> tuple:
    for game in events_odds:
        game_home = (game.get("home_team") or "").lower()
        game_away = (game.get("away_team") or "").lower()
        if home.lower() not in game_home and game_home not in home.lower():
            continue
        if away.lower() not in game_away and game_away not in away.lower():
            continue
        spread = None
        total = None
        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market.get("key") == "spreads" and spread is None:
                    for o in market.get("outcomes", []):
                        if home.lower() in (o.get("name") or "").lower():
                            spread = o.get("point", 0.0)
                if market.get("key") == "totals" and total is None:
                    for o in market.get("outcomes", []):
                        if o.get("name") == "Over":
                            total = o.get("point", 164.0)
        return (spread if spread is not None else None, total if total is not None else None)
    return None, None


@router.get("/edges")
def wnba_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    from wnba_data import get_team_stats, TEAM_IDS, get_wnba_events
    from wnba_predictor import WNBAPredictionEngine
    from services.odds_parser import get_live_odds
    engine = WNBAPredictionEngine()
    events = get_wnba_events()
    events_odds = get_live_odds("wnba")
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
        spread_line, over_under = _get_spread_and_total(events_odds, home, away)
        spread_line = spread_line if spread_line is not None else 0.0
        over_under = over_under if over_under is not None else 164.0
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, spread_line=spread_line, over_under=over_under, simulations=simulations)
        implied_home, implied_away = get_market_implied(events_odds, home, away)
        edge_home = pred.home_win_prob - implied_home
        edge_away = pred.away_win_prob - implied_away
        best_edge = max(edge_home, edge_away)
        if best_edge < min_edge:
            continue
        label = f"{away} @ {home}"
        bet_label = f"{home} ML" if pred.home_win_prob > pred.away_win_prob else f"{away} ML"
        bet_prob = pred.home_win_prob if edge_home >= edge_away else pred.away_win_prob
        bet_odds = round(-(bet_prob / (100 - bet_prob)) * 100) if bet_prob >= 50 else round(((100 - bet_prob) / bet_prob) * 100)
        pred_margin = round(pred.projected_home - pred.projected_away, 1)
        results.append({
            "game": label, "bet": bet_label, "model_prob": pred.home_win_prob,
            "implied_prob": implied_home if edge_home >= edge_away else implied_away,
            "edge": round(best_edge / 100, 4), "odds": bet_odds,
            "projected": f"{pred.projected_home}-{pred.projected_away}",
            "home_record": pred.home_record, "away_record": pred.away_record,
            "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            "pred_margin": pred_margin,
            "posted_spread": spread_line if spread_line != 0.0 else None,
            "spread_pick": (f"{home} -{abs(spread_line)}" if pred_margin > 0 else f"{away} +{abs(spread_line)}") if spread_line != 0.0 else None,
            "spread_cover_prob": pred.home_cover_prob if pred_margin > 0 else pred.away_cover_prob,
            "spread_edge": round(pred_margin - spread_line, 1) if spread_line != 0.0 else None,
            "projected_total": pred.projected_total,
            "posted_total": over_under if over_under != 164.0 else None,
            "over_prob": pred.over_prob, "under_prob": pred.under_prob,
        })
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
            home: [{"name": p.name, "position": p.position, "status": p.status} for p in (home_roster.players[:10] if home_roster else [])],
            away: [{"name": p.name, "position": p.position, "status": p.status} for p in (away_roster.players[:10] if away_roster else [])],
        },
    }


@router.get("/predictions")
def wnba_predictions(simulations: int = Query(default=10000)):
    from wnba_data import get_team_stats, TEAM_IDS, get_wnba_events
    from wnba_predictor import WNBAPredictionEngine
    from services.odds_parser import get_live_odds
    engine = WNBAPredictionEngine()
    events = get_wnba_events()
    events_odds = get_live_odds("wnba")
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
        spread_line, over_under = _get_spread_and_total(events_odds, home, away)
        spread_line = spread_line if spread_line is not None else 0.0
        over_under = over_under if over_under is not None else 164.0
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, spread_line=spread_line, over_under=over_under, simulations=simulations)
        implied_home, implied_away = get_market_implied(events_odds, home, away)
        e_home = pred.home_win_prob - implied_home
        e_away = pred.away_win_prob - implied_away
        best_edge = max(e_home, e_away)
        label = f"{away} @ {home}"
        bet_label = f"{home} ML" if e_home >= e_away else f"{away} ML"
        bet_prob = pred.home_win_prob if e_home >= e_away else pred.away_win_prob
        bet_odds = round(-(bet_prob / (100 - bet_prob)) * 100) if bet_prob >= 50 else round(((100 - bet_prob) / bet_prob) * 100)
        pred_margin = round(pred.projected_home - pred.projected_away, 1)
        results.append({
            "game": label, "bet": bet_label, "model_prob": pred.home_win_prob,
            "implied_prob": implied_home if e_home >= e_away else implied_away,
            "edge": round(best_edge / 100, 4), "odds": bet_odds,
            "projected": f"{pred.projected_home}-{pred.projected_away}",
            "home_record": pred.home_record, "away_record": pred.away_record,
            "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            "pred_margin": pred_margin,
            "posted_spread": spread_line if spread_line != 0.0 else None,
            "spread_pick": (f"{home} -{abs(spread_line)}" if pred_margin > 0 else f"{away} +{abs(spread_line)}") if spread_line != 0.0 else None,
            "spread_cover_prob": pred.home_cover_prob if pred_margin > 0 else pred.away_cover_prob,
            "spread_edge": round(pred_margin - spread_line, 1) if spread_line != 0.0 else None,
            "projected_total": pred.projected_total,
            "posted_total": over_under if over_under != 164.0 else None,
            "over_prob": pred.over_prob, "under_prob": pred.under_prob,
        })
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}