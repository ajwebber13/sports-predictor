"""
app/api/routes_wnba.py
=======================
WNBA-specific FastAPI endpoints.

Routes:
  GET /wnba/edges       - Team game edges
  GET /wnba/props       - Player prop edges
  GET /wnba/preview     - Full game preview with roster context
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import APIRouter, Query
from wnba_data import get_team_stats, get_roster, TEAM_IDS
from wnba_predictor import WNBAPredictionEngine
from wnba_props import get_wnba_prop_edges, get_wnba_events
from odds_parser import american_to_implied

import requests, os as _os

router = APIRouter()
engine = WNBAPredictionEngine()

API_KEY = _os.getenv("ODDS_API_KEY", "")


def _get_wnba_lines(home_team: str, away_team: str) -> tuple:
    """Get live spread and moneyline for a WNBA game."""
    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/basketball_wnba/odds",
            params={
                "apiKey":     API_KEY,
                "regions":    "us",
                "markets":    "spreads,h2h,totals",
                "bookmakers": "fanduel,draftkings",
                "oddsFormat": "american",
            },
            timeout=10,
        )
        games = r.json()
        for game in games:
            if game["home_team"] == home_team and game["away_team"] == away_team:
                spread = 0.0
                total  = 164.0
                ml_home = -110
                ml_away = -110
                for bm in game.get("bookmakers", []):
                    for market in bm.get("markets", []):
                        if market["key"] == "spreads":
                            for o in market["outcomes"]:
                                if o["name"] == home_team:
                                    spread = o.get("point", 0.0)
                        if market["key"] == "totals":
                            for o in market["outcomes"]:
                                if o["name"] == "Over":
                                    total = o.get("point", 164.0)
                        if market["key"] == "h2h":
                            for o in market["outcomes"]:
                                if o["name"] == home_team:
                                    ml_home = o["price"]
                                elif o["name"] == away_team:
                                    ml_away = o["price"]
                return spread, total, ml_home, ml_away
    except:
        pass
    return 0.0, 164.0, -110, -110


@router.get("/wnba/edges")
def wnba_edges(
    simulations: int = Query(default=10000),
    min_edge:    float = Query(default=3.0),
):
    """Returns WNBA game edges sorted by model vs market probability."""
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

        spread, total, ml_home, ml_away = _get_wnba_lines(home, away)

        pred = engine.predict(
            home_stats=home_stats,
            away_stats=away_stats,
            spread_line=spread,
            over_under=total,
            simulations=simulations,
        )

        implied_home = round(american_to_implied(ml_home) * 100, 1)
        implied_away = round(american_to_implied(ml_away) * 100, 1)
        edge_home = round(pred.home_win_prob - implied_home, 2)
        edge_away = round(pred.away_win_prob - implied_away, 2)

        game_label = f"{away} @ {home}"

        if edge_home >= min_edge:
            results.append({
                "game":          game_label,
                "bet":           f"{home} ML",
                "odds":          ml_home,
                "model_prob":    pred.home_win_prob,
                "implied_prob":  implied_home,
                "edge":          round(edge_home / 100, 4),
                "spread":        spread,
                "total":         total,
                "projected":     f"{pred.projected_home}-{pred.projected_away}",
                "cover_prob":    pred.home_cover_prob,
                "home_record":   pred.home_record,
                "away_record":   pred.away_record,
                "home_rest":     pred.home_rest_days,
                "away_rest":     pred.away_rest_days,
                "net_rating_home": pred.home_net_rating,
                "net_rating_away": pred.away_net_rating,
            })

        if edge_away >= min_edge:
            results.append({
                "game":          game_label,
                "bet":           f"{away} ML",
                "odds":          ml_away,
                "model_prob":    pred.away_win_prob,
                "implied_prob":  implied_away,
                "edge":          round(edge_away / 100, 4),
                "spread":        spread,
                "total":         total,
                "projected":     f"{pred.projected_home}-{pred.projected_away}",
                "cover_prob":    pred.away_cover_prob,
                "home_record":   pred.home_record,
                "away_record":   pred.away_record,
                "home_rest":     pred.home_rest_days,
                "away_rest":     pred.away_rest_days,
                "net_rating_home": pred.home_net_rating,
                "net_rating_away": pred.away_net_rating,
            })

    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}


@router.get("/wnba/props")
def wnba_props(min_edge: float = Query(default=3.0)):
    """Returns WNBA player prop edges."""
    edges = get_wnba_prop_edges(min_edge=min_edge)
    return {"count": len(edges), "props": edges}


@router.get("/wnba/preview")
def wnba_preview(home: str, away: str, simulations: int = Query(default=10000)):
    """Full game preview with prediction, roster, and prop context."""
    if home not in TEAM_IDS or away not in TEAM_IDS:
        return {"error": f"Unknown team. Available: {list(TEAM_IDS.keys())}"}

    home_stats = get_team_stats(home)
    away_stats = get_team_stats(away)

    if not home_stats or not away_stats:
        return {"error": "Could not fetch team stats from ESPN"}

    spread, total, ml_home, ml_away = _get_wnba_lines(home, away)

    pred = engine.predict(
        home_stats=home_stats,
        away_stats=away_stats,
        spread_line=spread,
        over_under=total,
        simulations=simulations,
    )

    home_roster = get_roster(home)
    away_roster = get_roster(away)

    return {
        "prediction": pred.to_dict(),
        "lines": {
            "spread": spread,
            "total":  total,
            "ml_home": ml_home,
            "ml_away": ml_away,
        },
        "rosters": {
            home: [{"name": p.name, "position": p.position, "status": p.status}
                   for p in (home_roster.players[:10] if home_roster else [])],
            away: [{"name": p.name, "position": p.position, "status": p.status}
                   for p in (away_roster.players[:10] if away_roster else [])],
        },
    }
