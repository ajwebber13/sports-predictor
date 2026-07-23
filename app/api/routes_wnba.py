from fastapi import APIRouter, Query
import sys
import os

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/wnba", tags=["WNBA"])

# Breakeven win% for standard -110 juice — used as the baseline "no edge"
# probability for spread/total picks, same way implied_home/implied_away
# already serves that role for moneyline. Not pulled from the odds feed
# per-game since spread/total prices are usually near -110 either way and
# the feed doesn't always carry them cleanly (see _get_market_details).
BREAKEVEN_PCT = 52.4


def get_market_implied(events_odds: list, home: str, away: str) -> tuple:
    """Returns (implied_home_pct, implied_away_pct, real_home_odds, real_away_odds).
    The real_* odds are the actual American price pulled from the odds feed —
    use these for display, never a price synthesized from the model's own
    probability (that number will always look "consistent" with the edge %
    since it's derived from it, even when it doesn't match any real book).

    implied_home_pct/implied_away_pct are NO-VIG (fair) probabilities —
    renormalized to sum to 100%. Real market odds sum to ~104-106% (the
    vig); comparing model_prob against the raw un-normalized number
    overstates the bookmaker's cut as if it were part of your real edge.
    """
    from services.odds_parser import american_to_implied
    home_pairs = []  # (implied_prob, raw_price)
    away_pairs = []
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
                        home_pairs.append((prob, price))
                    elif away.lower() in name:
                        away_pairs.append((prob, price))
    if not home_pairs or not away_pairs:
        # No real odds found — fall back to a true 50/50, not 52.4/52.4
        # (52.4/52.4 sums to 104.8%, which isn't a valid probability pair)
        return 50.0, 50.0, -110, -110
    home_pairs.sort(key=lambda x: x[0])
    away_pairs.sort(key=lambda x: x[0])
    h_prob, h_price = home_pairs[len(home_pairs) // 2]
    a_prob, a_price = away_pairs[len(away_pairs) // 2]

    # Remove vig: renormalize so both sides sum to exactly 100%.
    total = h_prob + a_prob
    h_fair = round(h_prob / total * 100, 1)
    a_fair = round(a_prob / total * 100, 1)
    return h_fair, a_fair, h_price, a_price


def _get_market_details(events_odds: list, home: str, away: str) -> dict:
    """Pulls posted spread/total LINES *and* their real prices from the odds
    feed for one matchup. Replaces the old _get_spread_and_total(), which
    only pulled the lines — spread/total bets logged from this route had no
    real price to attach, unlike moneyline (get_market_implied already did
    this correctly for h2h). Missing prices fall back to -110, the standard
    default, same convention get_market_implied uses for missing h2h.

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


def _build_bets_for_game(home: str, away: str, pred, events_odds: list, min_edge: float) -> list:
    """Turns one WNBAPrediction into up to 3 bet dicts — moneyline, spread,
    total — instead of the old single moneyline-only dict. Spread/total are
    only included when a real posted line exists AND the model's edge
    clears min_edge, same bar moneyline already uses. Every dict carries
    market/pick/line so database.log_prediction() can log each one as its
    own row (predictions table is now keyed on date, sport, game, market —
    see database.py's 2026-07-20 update).

    NOTE: shared by both /edges and /predictions — previously this logic
    (moneyline-only) was duplicated verbatim in both route functions with
    no way to keep them in sync. Consolidating here means a future change
    only has to happen once.
    """
    implied_home, implied_away, real_odds_home, real_odds_away = get_market_implied(events_odds, home, away)
    market = _get_market_details(events_odds, home, away)

    edge_home = pred.home_win_prob - implied_home
    edge_away = pred.away_win_prob - implied_away
    best_edge = max(edge_home, edge_away)
    label = f"{away} @ {home}"
    pred_margin = round(pred.projected_home - pred.projected_away, 1)

    bets = []

    # ---- Moneyline ----
    ml_pick = home if edge_home >= edge_away else away
    ml_prob = pred.home_win_prob if edge_home >= edge_away else pred.away_win_prob
    ml_odds = real_odds_home if edge_home >= edge_away else real_odds_away
    ml_implied = implied_home if edge_home >= edge_away else implied_away
    bets.append({
        "game": label, "market": "moneyline",
        "bet": f"{ml_pick} ML", "pick": ml_pick, "line": None,
        "model_prob": ml_prob, "implied_prob": ml_implied,
        "home_win_prob": round(pred.home_win_prob, 1), "away_win_prob": round(pred.away_win_prob, 1),
        "edge": round(best_edge / 100, 4), "odds": ml_odds,
        "projected": f"{pred.projected_home}-{pred.projected_away}",
        "projected_home": pred.projected_home, "projected_away": pred.projected_away,
        "projected_margin": pred_margin, "projected_total": pred.projected_total,
        "home_record": pred.home_record, "away_record": pred.away_record,
        "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
    })

    # ---- Spread ----
    # spread_line is the HOME team's posted number (e.g. -3.5 = home
    # favored by 3.5). pred_margin > 0 means the model favors home to
    # cover, so the pick is home at their own posted number; otherwise
    # the pick is away at the mirrored number.
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
def wnba_edges(simulations: int = Query(default=30000), min_edge: float = Query(default=3.0)):
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
        market = _get_market_details(events_odds, home, away)
        spread_line = market["spread_line"] if market["spread_line"] is not None else 0.0
        over_under = market["total_line"] if market["total_line"] is not None else 164.0
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, spread_line=spread_line, over_under=over_under, simulations=simulations)

        bets, best_edge = _build_bets_for_game(home, away, pred, events_odds, min_edge)
        # Games with no qualifying market at all (moneyline edge below
        # min_edge, and spread/total either missing or also below
        # min_edge) are dropped entirely — same bar the old code used
        # (best_edge < min_edge -> skip), now checked after building
        # instead of before, since spread/total could still qualify even
        # when moneyline alone wouldn't have.
        if best_edge < min_edge and len(bets) == 1:
            continue
        results.extend(bets)
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}


@router.get("/preview")
def wnba_preview(home: str, away: str, simulations: int = Query(default=30000)):
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
def wnba_predictions(simulations: int = Query(default=30000), min_edge: float = Query(default=0.0)):
    """Same multi-market build as /edges, but with min_edge defaulting to
    0.0 — this endpoint is meant to show ALL games regardless of edge
    (used for the website's daily-intelligence exports), so it keeps that
    behavior for moneyline while still gating spread/total on whatever
    min_edge the caller passes (0.0 by default = show everything)."""
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
        market = _get_market_details(events_odds, home, away)
        spread_line = market["spread_line"] if market["spread_line"] is not None else 0.0
        over_under = market["total_line"] if market["total_line"] is not None else 164.0
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, spread_line=spread_line, over_under=over_under, simulations=simulations)

        bets, _ = _build_bets_for_game(home, away, pred, events_odds, min_edge)
        results.extend(bets)
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}
