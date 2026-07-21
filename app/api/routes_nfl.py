from fastapi import APIRouter, Query
import sys
import os

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/nfl", tags=["NFL"])

DEFAULT_TOTAL = 44.0

# Breakeven win% for standard -110 juice — used as the "no edge" baseline
# for spread/total picks, same convention routes_wnba.py uses. CFB/NFL's
# moneyline odds are already synthesized from the model's own probability
# (see bet_odds below) rather than pulled from a real book price — that's
# pre-existing behavior, unchanged here.
BREAKEVEN_PCT = 52.4


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


def _get_market_details(events_odds: list, home: str, away: str) -> dict:
    """Pulls posted spread/total LINES *and* their real prices from the
    odds feed for one matchup. Replaces the old _get_spread_and_total(),
    which only pulled the lines — spread/total bets logged from this
    route had no real price to attach. Missing prices fall back to -110.

    Returns:
        {
            "spread_line": float | None,      # home team's posted number
            "home_spread_odds": int,
            "away_spread_odds": int,
            "total_line": float | None,
            "over_odds": int,
            "under_odds": int,
        }
    """
    out = {
        "spread_line": None, "home_spread_odds": -110, "away_spread_odds": -110,
        "total_line": None, "over_odds": -110, "under_odds": -110,
    }
    for game in events_odds:
        game_home = (game.get("home_team") or "").lower()
        game_away = (game.get("away_team") or "").lower()
        if home.lower() not in game_home and game_home not in home.lower():
            continue
        if away.lower() not in game_away and game_away not in away.lower():
            continue
        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                key = market.get("key")
                if key == "spreads":
                    for o in market.get("outcomes", []):
                        name = (o.get("name") or "").lower()
                        price = o.get("price", -110)
                        point = o.get("point")
                        if home.lower() in name:
                            if out["spread_line"] is None:
                                out["spread_line"] = point
                            out["home_spread_odds"] = price
                        elif away.lower() in name:
                            out["away_spread_odds"] = price
                elif key == "totals":
                    for o in market.get("outcomes", []):
                        name = (o.get("name") or "")
                        price = o.get("price", -110)
                        point = o.get("point")
                        if name == "Over":
                            if out["total_line"] is None:
                                out["total_line"] = point
                            out["over_odds"] = price
                        elif name == "Under":
                            out["under_odds"] = price
        return out
    return out


def _build_bets_for_game(home: str, away: str, pred, events_odds: list, min_edge: float) -> tuple:
    """Turns one NFLPrediction into up to 3 bet dicts — moneyline, spread,
    total — instead of the old single moneyline-only dict. Spread/total
    are only included when a real posted line exists AND the model's edge
    clears min_edge, same bar moneyline uses. Shared by /edges and
    /predictions so both stay in sync (previously duplicated verbatim)."""
    implied_home, implied_away = get_market_implied(events_odds, home, away)
    market = _get_market_details(events_odds, home, away)

    edge_home = pred.home_win_prob - implied_home
    edge_away = pred.away_win_prob - implied_away
    best_edge = max(edge_home, edge_away)
    label = f"{away} @ {home}"
    pred_margin = round(pred.projected_home - pred.projected_away, 1)

    def synth_odds(prob):
        # Existing behavior, unchanged: fair odds derived from the
        # model's own probability, since this route has no real
        # moneyline book price to fall back on (unlike WNBA).
        return round(-(prob / (100 - prob)) * 100) if prob >= 50 else round(((100 - prob) / prob) * 100)

    bets = []

    # ---- Moneyline ----
    ml_pick = home if edge_home >= edge_away else away
    ml_prob = pred.home_win_prob if edge_home >= edge_away else pred.away_win_prob
    ml_implied = implied_home if edge_home >= edge_away else implied_away
    bets.append({
        "game": label, "market": "moneyline",
        "bet": f"{ml_pick} ML", "pick": ml_pick, "line": None,
        "model_prob": ml_prob, "implied_prob": ml_implied,
        "edge": round(best_edge / 100, 4), "odds": synth_odds(ml_prob),
        "projected": f"{pred.projected_home}-{pred.projected_away}",
        "projected_home": pred.projected_home, "projected_away": pred.projected_away,
        "projected_margin": pred_margin, "projected_total": pred.projected_total,
        "home_record": pred.home_record, "away_record": pred.away_record,
        "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
    })

    # ---- Spread ----
    if market["spread_line"] is not None:
        home_favored_to_cover = pred_margin > 0
        spread_pick = home if home_favored_to_cover else away
        spread_line_for_pick = market["spread_line"] if home_favored_to_cover else -market["spread_line"]
        spread_prob = pred.home_cover_prob if home_favored_to_cover else pred.away_cover_prob
        spread_odds = market["home_spread_odds"] if home_favored_to_cover else market["away_spread_odds"]
        spread_edge_pct = spread_prob - BREAKEVEN_PCT
        if spread_edge_pct >= min_edge:
            sign = "+" if spread_line_for_pick > 0 else ""
            bets.append({
                "game": label, "market": "spread",
                "bet": f"{spread_pick} {sign}{spread_line_for_pick}",
                "pick": spread_pick, "line": spread_line_for_pick,
                "model_prob": spread_prob, "implied_prob": BREAKEVEN_PCT,
                "edge": round(spread_edge_pct / 100, 4), "odds": spread_odds,
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "projected_home": pred.projected_home, "projected_away": pred.projected_away,
                "projected_margin": pred_margin, "projected_total": pred.projected_total,
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            })

    # ---- Total ----
    if market["total_line"] is not None:
        over_edge_pct = pred.over_prob - BREAKEVEN_PCT
        under_edge_pct = pred.under_prob - BREAKEVEN_PCT
        if max(over_edge_pct, under_edge_pct) >= min_edge:
            total_pick = "Over" if over_edge_pct >= under_edge_pct else "Under"
            total_prob = pred.over_prob if total_pick == "Over" else pred.under_prob
            total_odds = market["over_odds"] if total_pick == "Over" else market["under_odds"]
            total_edge_pct = max(over_edge_pct, under_edge_pct)
            bets.append({
                "game": label, "market": "total",
                "bet": f"{total_pick} {market['total_line']}",
                "pick": total_pick, "line": market["total_line"],
                "model_prob": total_prob, "implied_prob": BREAKEVEN_PCT,
                "edge": round(total_edge_pct / 100, 4), "odds": total_odds,
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "projected_home": pred.projected_home, "projected_away": pred.projected_away,
                "projected_margin": pred_margin, "projected_total": pred.projected_total,
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            })

    return bets, best_edge


@router.get("/edges")
def nfl_edges(simulations: int = Query(default=50000), min_edge: float = Query(default=3.0)):
    from nfl_data import get_team_stats, NFL_TEAM_IDS, get_nfl_events
    from nfl_predictor import NFLPredictionEngine
    from services.odds_parser import get_live_odds
    engine = NFLPredictionEngine()
    events = get_nfl_events()
    events_odds = get_live_odds("nfl")
    results = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home not in NFL_TEAM_IDS or away not in NFL_TEAM_IDS:
            continue
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        market = _get_market_details(events_odds, home, away)
        spread_line = market["spread_line"] if market["spread_line"] is not None else 0.0
        over_under = market["total_line"] if market["total_line"] is not None else DEFAULT_TOTAL
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, spread_line=spread_line, over_under=over_under, simulations=simulations)

        bets, best_edge = _build_bets_for_game(home, away, pred, events_odds, min_edge)
        if best_edge < min_edge and len(bets) == 1:
            continue
        results.extend(bets)
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}


@router.get("/preview")
def nfl_preview(home: str, away: str, simulations: int = Query(default=50000)):
    from nfl_data import get_team_stats, NFL_TEAM_IDS
    from nfl_predictor import NFLPredictionEngine
    if home not in NFL_TEAM_IDS or away not in NFL_TEAM_IDS:
        return {"error": f"Unknown team. Available: {list(NFL_TEAM_IDS.keys())}"}
    home_stats = get_team_stats(home)
    away_stats = get_team_stats(away)
    if not home_stats or not away_stats:
        return {"error": "Could not fetch team stats from ESPN"}
    engine = NFLPredictionEngine()
    pred = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
    return {"prediction": pred.to_dict()}


@router.get("/predictions")
def nfl_predictions(simulations: int = Query(default=50000), min_edge: float = Query(default=0.0)):
    """Same multi-market build as /edges, but min_edge defaults to 0.0 —
    this endpoint shows ALL games regardless of edge (used for morning
    briefings), same convention now shared with routes_wnba.py."""
    from nfl_data import get_team_stats, NFL_TEAM_IDS, get_nfl_events
    from nfl_predictor import NFLPredictionEngine
    from services.odds_parser import get_live_odds
    engine = NFLPredictionEngine()
    events = get_nfl_events()
    events_odds = get_live_odds("nfl")
    results = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home not in NFL_TEAM_IDS or away not in NFL_TEAM_IDS:
            continue
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        market = _get_market_details(events_odds, home, away)
        spread_line = market["spread_line"] if market["spread_line"] is not None else 0.0
        over_under = market["total_line"] if market["total_line"] is not None else DEFAULT_TOTAL
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, spread_line=spread_line, over_under=over_under, simulations=simulations)

        bets, _ = _build_bets_for_game(home, away, pred, events_odds, min_edge)
        results.extend(bets)
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}