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
            results.append({
                "game": label, "bet": f"{home} ML", "odds": odds_home,
                "model_prob": m_home, "implied_prob": i_home,
                "edge": round(e_home / 100, 4), "spread": spread_line,
                "net_rating_home": round(home_net, 1),
                "net_rating_away": round(away_net, 1),
            })
        if e_away >= min_edge:
            results.append({
                "game": label, "bet": f"{away} ML", "odds": odds_away,
                "model_prob": m_away, "implied_prob": i_away,
                "edge": round(e_away / 100, 4), "spread": spread_line,
                "net_rating_home": round(home_net, 1),
                "net_rating_away": round(away_net, 1),
            })

    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"sport": "nba", "count": len(results), "best_bets": results}


@app.get("/wnba/edges")
def wnba_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from wnba_data import get_team_stats, TEAM_IDS
    from wnba_predictor import WNBAPredictionEngine
    from services.odds_parser import get_live_odds, american_to_implied
    engine = WNBAPredictionEngine()
    events = get_live_odds("wnba")
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
        e_home  = round(pred.home_win_prob - implied, 2)
        e_away  = round(pred.away_win_prob - implied, 2)
        label   = f"{away} @ {home}"
        if e_home >= min_edge:
            results.append({"game": label, "bet": f"{home} ML", "model_prob": pred.home_win_prob,
                "implied_prob": implied, "edge": round(e_home / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days})
        if e_away >= min_edge:
            results.append({"game": label, "bet": f"{away} ML", "model_prob": pred.away_win_prob,
                "implied_prob": implied, "edge": round(e_away / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days})
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
            pred   = engine.predict(
                profile_a    = NFL_PROFILES[home],
                profile_b    = NFL_PROFILES[away],
                spread_line  = spread_line,
                over_under   = over_under,
                odds_a       = odds_home,
                odds_b       = odds_away,
                neutral_site = False,
                a_is_home    = True,
                context      = GameContext(),
                simulations  = simulations,
            )
            m_home = pred.team_a_win_prob
            m_away = pred.team_b_win_prob
            e_home = round(m_home - i_home, 2)
            e_away = round(m_away - i_away, 2)

            if e_home >= min_edge:
                results.append({
                    "game": label, "bet": f"{home} ML", "odds": odds_home,
                    "model_prob": round(m_home, 1), "implied_prob": i_home,
                    "edge": round(e_home / 100, 4),
                    "projected": f"{round(pred.projected_pts_a, 1)}-{round(pred.projected_pts_b, 1)}",
                })
            if e_away >= min_edge:
                results.append({
                    "game": label, "bet": f"{away} ML", "odds": odds_away,
                    "model_prob": round(m_away, 1), "implied_prob": i_away,
                    "edge": round(e_away / 100, 4),
                    "projected": f"{round(pred.projected_pts_b, 1)}-{round(pred.projected_pts_a, 1)}",
                })
        except:
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

    def normalize(name):
        return NAME_MAP.get(name, name)

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
                profile_a    = TEAM_PROFILES[home],
                profile_b    = TEAM_PROFILES[away],
                spread_line  = spread_line,
                over_under   = over_under,
                odds_a       = odds_home,
                odds_b       = odds_away,
                neutral_site = False,
                a_is_home    = True,
                context      = GameContext(),
                simulations  = simulations,
            )
            m_home = pred.team_a_win_prob
            m_away = pred.team_b_win_prob
            e_home = round(m_home - i_home, 2)
            e_away = round(m_away - i_away, 2)

            if e_home >= min_edge:
                results.append({
                    "game": label, "bet": f"{home} ML", "odds": odds_home,
                    "model_prob": round(m_home, 1), "implied_prob": i_home,
                    "edge": round(e_home / 100, 4),
                    "projected": f"{round(pred.projected_pts_a, 1)}-{round(pred.projected_pts_b, 1)}",
                })
            if e_away >= min_edge:
                results.append({
                    "game": label, "bet": f"{away} ML", "odds": odds_away,
                    "model_prob": round(m_away, 1), "implied_prob": i_away,
                    "edge": round(e_away / 100, 4),
                    "projected": f"{round(pred.projected_pts_b, 1)}-{round(pred.projected_pts_a, 1)}",
                })
        except:
            continue

    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"sport": "ncaaf", "count": len(results), "best_bets": results}

@app.get("/ncaab/edges")
def ncaab_edges(simulations: int = Query(default=10000), min_edge: float = Query(default=3.0)):
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    from ncaab_data import get_team_stats, get_ncaab_events
    from ncaab_predictor import NCAABPredictionEngine
    from services.odds_parser import american_to_implied
    engine = NCAABPredictionEngine()
    events = get_ncaab_events()
    results = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
        implied = round(american_to_implied(-110) * 100, 1)
        e_home  = round(pred.home_win_prob - implied, 2)
        e_away  = round(pred.away_win_prob - implied, 2)
        label   = f"{away} @ {home}"
        if e_home >= min_edge:
            results.append({"game": label, "bet": f"{home} ML", "model_prob": pred.home_win_prob,
                "implied_prob": implied, "edge": round(e_home / 100, 4),
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days})
        if e_away >= min_edge:
            results.append({"game": label, "bet": f"{away} ML", "model_prob": pred.away_win_prob,
                "implied_prob": implied, "edge": round(e_away / 100, 4),
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

