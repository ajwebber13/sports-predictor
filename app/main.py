from fastapi import FastAPI, Query
from app.api.routes_predict import router as predict_router
from app.api.routes_slate import router as slate_router
from app.api.routes_edges import router as edges_router

app = FastAPI(title="Sports Betting Model API", version="1.0")

app.include_router(predict_router, prefix="/predict", tags=["Predict"])
app.include_router(slate_router, prefix="/slate", tags=["Slate"])
app.include_router(edges_router, prefix="/edges", tags=["Edges"])


@app.get("/")
def root():
    return {"status": "running"}


@app.get("/nba/edges")
def nba_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    import sys, os, math
    sys.path.insert(0, os.path.abspath("."))
    from services.odds_parser import get_live_odds, american_to_implied
    from data.nba_profiles import NBA_PROFILES
    games = get_live_odds("nba")
    results = []
    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        if home not in NBA_PROFILES or away not in NBA_PROFILES:
            continue
        odds_home, odds_away = -110, -110
        spread_line = 0.0
        for bm in game.get("bookmakers", []):
            for m in bm.get("markets", []):
                if m["key"] == "h2h":
                    for o in m["outcomes"]:
                        if o["name"] == home: odds_home = o["price"]
                        elif o["name"] == away: odds_away = o["price"]
                if m["key"] == "spreads":
                    for o in m["outcomes"]:
                        if o["name"] == home: spread_line = o.get("point", 0.0)
        home_net = NBA_PROFILES[home].pts_off - NBA_PROFILES[home].pts_def
        away_net = NBA_PROFILES[away].pts_off - NBA_PROFILES[away].pts_def
        diff    = (home_net - away_net) + 3.0
        m_home  = round(1 / (1 + math.exp(-diff / 8.0)) * 100, 1)
        m_away  = round(100 - m_home, 1)
        i_home  = round(american_to_implied(odds_home) * 100, 1)
        i_away  = round(american_to_implied(odds_away) * 100, 1)
        e_home  = round(m_home - i_home, 2)
        e_away  = round(m_away - i_away, 2)
        label   = f"{away} @ {home}"
        if e_home >= min_edge:
            results.append({"game": label, "bet": f"{home} ML", "odds": odds_home,
                "model_prob": m_home, "implied_prob": i_home,
                "edge": round(e_home / 100, 4), "spread": spread_line,
                "net_rating_home": round(home_net, 1), "net_rating_away": round(away_net, 1)})
        if e_away >= min_edge:
            results.append({"game": label, "bet": f"{away} ML", "odds": odds_away,
                "model_prob": m_away, "implied_prob": i_away,
                "edge": round(e_away / 100, 4), "spread": spread_line,
                "net_rating_home": round(home_net, 1), "net_rating_away": round(away_net, 1)})
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"sport": "nba", "count": len(results), "best_bets": results}


@app.get("/wnba/edges")
def wnba_edges(
    simulations:    int   = Query(default=10000),
    min_edge:       float = Query(default=3.0),
    include_totals: bool  = Query(default=True),
):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from wnba_data import get_team_stats, TEAM_IDS, get_wnba_events
    from wnba_predictor import WNBAPredictionEngine
    from services.odds_parser import american_to_implied, get_live_odds, parse_moneyline

    engine = WNBAPredictionEngine()
    events = get_wnba_events()

    # ── Live moneyline + over/under from Odds API ──
    odds_games  = get_live_odds("wnba")
    odds_lookup = {}
    ou_lookup   = {}
    for og in odds_games:
        home_name = og.get("home_team", "")
        away_name = og.get("away_team", "")
        ml = parse_moneyline(og)
        if ml:
            odds_lookup[home_name] = ml
            odds_lookup[away_name] = ml
        # Pull over/under line from bookmakers
        for bm in og.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market["key"] == "totals":
                    for outcome in market.get("outcomes", []):
                        if outcome["name"] == "Over":
                            game_key = f"{away_name}@{home_name}"
                            ou_lookup[game_key] = outcome.get("point", None)

    # ── Injury data ──
    try:
        from injury_check import get_injuries
        injuries = get_injuries("wnba")
    except Exception:
        injuries = {}

    MAX_SANE_EDGE = 25.0
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

        # Get live over/under if available
        game_key   = f"{away}@{home}"
        book_total = ou_lookup.get(game_key, None)

        pred = engine.predict(
            home_stats  = home_stats,
            away_stats  = away_stats,
            simulations = simulations,
            over_under  = book_total if book_total else 164.0,
        )

        ml_probs = odds_lookup.get(home) or odds_lookup.get(away)
        fallback = round(american_to_implied(-110) * 100, 1)
        i_home   = ml_probs.get(home, fallback) if ml_probs else fallback
        i_away   = ml_probs.get(away, fallback) if ml_probs else fallback

        e_home = round(pred.home_win_prob - i_home, 2)
        e_away = round(pred.away_win_prob - i_away, 2)

        # Never recommend model underdog
        if pred.home_win_prob < pred.away_win_prob:
            e_home = -999
        else:
            e_away = -999

        label    = f"{away} @ {home}"
        home_inj = ", ".join(injuries.get(home, []))
        away_inj = ", ".join(injuries.get(away, []))

        shared = {
            "game":          label,
            "projected":     f"{pred.projected_home}-{pred.projected_away}",
            "home_record":   pred.home_record,
            "away_record":   pred.away_record,
            "home_rest":     pred.home_rest_days,
            "away_rest":     pred.away_rest_days,
            "home_injuries": home_inj,
            "away_injuries": away_inj,
            "event_id":      event.get("event_id", ""),
        }

        # ── Moneyline edges ──
        if e_home >= min_edge and e_home <= MAX_SANE_EDGE:
            results.append({**shared,
                "bet": f"{home} ML", "bet_type": "ML",
                "model_prob": pred.home_win_prob, "implied_prob": i_home,
                "edge": round(e_home / 100, 4),
            })

        if e_away >= min_edge and e_away <= MAX_SANE_EDGE:
            results.append({**shared,
                "bet": f"{away} ML", "bet_type": "ML",
                "model_prob": pred.away_win_prob, "implied_prob": i_away,
                "edge": round(e_away / 100, 4),
            })

        # ── Totals edges (only when live book line available) ──
        if include_totals and book_total:
            implied_ou = round(american_to_implied(-110) * 100, 1)
            over_edge  = round(pred.over_prob - implied_ou, 2)
            under_edge = round(pred.under_prob - implied_ou, 2)

            if over_edge >= min_edge and over_edge <= MAX_SANE_EDGE:
                results.append({**shared,
                    "bet":          f"OVER {book_total}",
                    "bet_type":     "OU",
                    "model_prob":   pred.over_prob,
                    "implied_prob": implied_ou,
                    "edge":         round(over_edge / 100, 4),
                    "book_total":   book_total,
                    "proj_total":   round(pred.projected_total, 1),
                })

            if under_edge >= min_edge and under_edge <= MAX_SANE_EDGE:
                results.append({**shared,
                    "bet":          f"UNDER {book_total}",
                    "bet_type":     "OU",
                    "model_prob":   pred.under_prob,
                    "implied_prob": implied_ou,
                    "edge":         round(under_edge / 100, 4),
                    "book_total":   book_total,
                    "proj_total":   round(pred.projected_total, 1),
                })

    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}


@app.get("/wnba/preview")
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


@app.get("/nfl/edges")
def nfl_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from services.odds_parser import get_live_odds, american_to_implied
    from services.model_connector import _extract_lines
    from data.nfl_profiles import NFL_PROFILES
    from enhanced_predictor import EnhancedPredictionEngine
    from enhanced_data import GameContext
    engine = EnhancedPredictionEngine()
    games  = get_live_odds("nfl")
    results = []
    for game in games:
        home = game.get("home_team", "")
        away = game.get("away_team", "")
        if home not in NFL_PROFILES or away not in NFL_PROFILES:
            continue
        spread_line, over_under, odds_home, odds_away = _extract_lines(game)
        i_home = round(american_to_implied(odds_home) * 100, 1)
        i_away = round(american_to_implied(odds_away) * 100, 1)
        label  = f"{away} @ {home}"
        try:
            pred = engine.predict(
                profile_a=NFL_PROFILES[home], profile_b=NFL_PROFILES[away],
                spread_line=spread_line, over_under=over_under,
                odds_a=odds_home, odds_b=odds_away,
                neutral_site=False, a_is_home=True,
                context=GameContext(), simulations=simulations,
            )
            m_home = pred.team_a_win_prob
            m_away = pred.team_b_win_prob
            try:
                from ensemble_model import predict_game
                ens = predict_game(home, away, "nfl")
                if ens and ens.get("ensemble_home_prob"):
                    m_home = round((m_home * 0.5) + (ens["ensemble_home_prob"] * 0.5), 1)
                    m_away = round((m_away * 0.5) + (ens["ensemble_away_prob"] * 0.5), 1)
            except Exception:
                pass
            try:
                from elo_ratings import predict_with_elo
                elo_pred = predict_with_elo(home, away, "nfl")
                m_home   = round((m_home * 0.7) + (elo_pred["home_win_prob"] * 0.3), 1)
                m_away   = round((m_away * 0.7) + (elo_pred["away_win_prob"] * 0.3), 1)
            except Exception:
                pass
            try:
                from home_away_splits import get_split_adjustment
                home_split = get_split_adjustment(home, "nfl", is_home=True)
                away_split = get_split_adjustment(away, "nfl", is_home=False)
                if home_split != 0 or away_split != 0:
                    net_split = (home_split - away_split) * 0.01
                    m_home = round(min(max(m_home / 100 + net_split, 0.01), 0.99) * 100, 1)
                    m_away = round(100 - m_home, 1)
            except Exception:
                pass
            e_home = round(m_home - i_home, 2)
            e_away = round(m_away - i_away, 2)
            if e_home >= min_edge:
                results.append({"game": label, "bet": f"{home} ML", "odds": odds_home,
                    "model_prob": round(m_home, 1), "implied_prob": i_home,
                    "edge": round(e_home / 100, 4),
                    "projected": f"{round(pred.projected_pts_a, 1)}-{round(pred.projected_pts_b, 1)}"})
            if e_away >= min_edge:
                results.append({"game": label, "bet": f"{away} ML", "odds": odds_away,
                    "model_prob": round(m_away, 1), "implied_prob": i_away,
                    "edge": round(e_away / 100, 4),
                    "projected": f"{round(pred.projected_pts_b, 1)}-{round(pred.projected_pts_a, 1)}"})
        except Exception:
            continue
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"sport": "nfl", "count": len(results), "best_bets": results}


@app.get("/ncaaf/edges")
def ncaaf_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from services.odds_parser import get_live_odds, american_to_implied
    from services.model_connector import _extract_lines
    from data.team_profiles import TEAM_PROFILES
    from enhanced_predictor import EnhancedPredictionEngine
    from enhanced_data import GameContext
    NAME_MAP = {
        "LSU Tigers": "LSU", "Clemson Tigers": "Clemson",
        "Alabama Crimson Tide": "Alabama", "Georgia Bulldogs": "Georgia",
        "Ohio State Buckeyes": "Ohio State", "Michigan Wolverines": "Michigan",
        "Texas Longhorns": "Texas", "Oklahoma Sooners": "Oklahoma",
        "Notre Dame Fighting Irish": "Notre Dame",
        "Penn State Nittany Lions": "Penn State", "Oregon Ducks": "Oregon",
    }
    def normalize(name): return NAME_MAP.get(name, name)
    engine = EnhancedPredictionEngine()
    games  = get_live_odds("americanfootball_ncaaf")
    results = []
    for game in games:
        home = normalize(game.get("home_team", ""))
        away = normalize(game.get("away_team", ""))
        if home not in TEAM_PROFILES or away not in TEAM_PROFILES:
            continue
        spread_line, over_under, odds_home, odds_away = _extract_lines(game)
        i_home = round(american_to_implied(odds_home) * 100, 1)
        i_away = round(american_to_implied(odds_away) * 100, 1)
        label  = f"{away} @ {home}"
        try:
            pred = engine.predict(
                profile_a=TEAM_PROFILES[home], profile_b=TEAM_PROFILES[away],
                spread_line=spread_line, over_under=over_under,
                odds_a=odds_home, odds_b=odds_away,
                neutral_site=False, a_is_home=True,
                context=GameContext(), simulations=simulations,
            )
            m_home = pred.team_a_win_prob
            m_away = pred.team_b_win_prob
            try:
                from ensemble_model import predict_game
                ens = predict_game(home, away, "ncaaf")
                if ens and ens.get("ensemble_home_prob"):
                    m_home = round((m_home * 0.5) + (ens["ensemble_home_prob"] * 0.5), 1)
                    m_away = round((m_away * 0.5) + (ens["ensemble_away_prob"] * 0.5), 1)
            except Exception:
                pass
            try:
                from elo_ratings import predict_with_elo
                elo_pred = predict_with_elo(home, away, "ncaaf")
                m_home   = round((m_home * 0.7) + (elo_pred["home_win_prob"] * 0.3), 1)
                m_away   = round((m_away * 0.7) + (elo_pred["away_win_prob"] * 0.3), 1)
            except Exception:
                pass
            try:
                from home_away_splits import get_split_adjustment
                home_split = get_split_adjustment(home, "ncaaf", is_home=True)
                away_split = get_split_adjustment(away, "ncaaf", is_home=False)
                if home_split != 0 or away_split != 0:
                    net_split = (home_split - away_split) * 0.01
                    m_home = round(min(max(m_home / 100 + net_split, 0.01), 0.99) * 100, 1)
                    m_away = round(100 - m_home, 1)
            except Exception:
                pass
            e_home = round(m_home - i_home, 2)
            e_away = round(m_away - i_away, 2)
            if e_home >= min_edge:
                results.append({"game": label, "bet": f"{home} ML", "odds": odds_home,
                    "model_prob": round(m_home, 1), "implied_prob": i_home,
                    "edge": round(e_home / 100, 4),
                    "projected": f"{round(pred.projected_pts_a, 1)}-{round(pred.projected_pts_b, 1)}"})
            if e_away >= min_edge:
                results.append({"game": label, "bet": f"{away} ML", "odds": odds_away,
                    "model_prob": round(m_away, 1), "implied_prob": i_away,
                    "edge": round(e_away / 100, 4),
                    "projected": f"{round(pred.projected_pts_b, 1)}-{round(pred.projected_pts_a, 1)}"})
        except Exception:
            continue
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"sport": "ncaaf", "count": len(results), "best_bets": results}


@app.get("/ncaab/edges")
def ncaab_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from ncaab_data import get_team_stats, get_ncaab_events
    from ncaab_predictor import NCAABPredictionEngine
    from services.odds_parser import american_to_implied, get_live_odds, parse_moneyline

    engine = NCAABPredictionEngine()
    events = get_ncaab_events()

    odds_games  = get_live_odds("ncaab")
    odds_lookup = {}
    for og in odds_games:
        ml = parse_moneyline(og)
        if ml:
            odds_lookup[og.get("home_team", "")] = ml
            odds_lookup[og.get("away_team", "")] = ml

    results = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)

        ml_probs = odds_lookup.get(home) or odds_lookup.get(away)
        fallback = round(american_to_implied(-110) * 100, 1)
        i_home   = ml_probs.get(home, fallback) if ml_probs else fallback
        i_away   = ml_probs.get(away, fallback) if ml_probs else fallback

        home_prob = pred.home_win_prob
        away_prob = pred.away_win_prob

        try:
            from ensemble_model import predict_game
            ens = predict_game(home, away, "ncaab")
            if ens and ens.get("ensemble_home_prob"):
                home_prob = round((home_prob * 0.5) + (ens["ensemble_home_prob"] * 0.5), 1)
                away_prob = round((away_prob * 0.5) + (ens["ensemble_away_prob"] * 0.5), 1)
        except Exception:
            pass
        try:
            from elo_ratings import predict_with_elo
            elo_pred  = predict_with_elo(home, away, "ncaab")
            home_prob = round((home_prob * 0.7) + (elo_pred["home_win_prob"] * 0.3), 1)
            away_prob = round((away_prob * 0.7) + (elo_pred["away_win_prob"] * 0.3), 1)
        except Exception:
            pass
        try:
            from home_away_splits import get_split_adjustment
            home_split = get_split_adjustment(home, "ncaab", is_home=True)
            away_split = get_split_adjustment(away, "ncaab", is_home=False)
            if home_split != 0 or away_split != 0:
                net_split = (home_split - away_split) * 0.01
                home_prob = round(min(max(home_prob / 100 + net_split, 0.01), 0.99) * 100, 1)
                away_prob = round(100 - home_prob, 1)
        except Exception:
            pass

        e_home = round(home_prob - i_home, 2)
        e_away = round(away_prob - i_away, 2)
        label  = f"{away} @ {home}"

        if e_home >= min_edge:
            results.append({"game": label, "bet": f"{home} ML", "model_prob": pred.home_win_prob,
                "implied_prob": i_home, "edge": round(e_home / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days})
        if e_away >= min_edge:
            results.append({"game": label, "bet": f"{away} ML", "model_prob": pred.away_win_prob,
                "implied_prob": i_away, "edge": round(e_away / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days})

    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}


@app.get("/ncaab/preview")
def ncaab_preview(home: str, away: str, simulations: int = Query(default=10000)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from ncaab_data import get_team_stats, get_roster
    from ncaab_predictor import NCAABPredictionEngine
    home_stats = get_team_stats(home)
    away_stats = get_team_stats(away)
    if not home_stats:
        return {"error": f"Could not find team: {home}"}
    if not away_stats:
        return {"error": f"Could not find team: {away}"}
    engine = NCAABPredictionEngine()
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