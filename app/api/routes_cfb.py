from fastapi import APIRouter, Query
import sys
import os

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/cfb", tags=["CFB"])

DEFAULT_TOTAL = 52.0


def _fair_two_way_prob(picked_side_odds: int, other_side_odds: int) -> float:
    """Converts a two-sided real price into the fair (no-vig)
    probability of the picked side, added 2026-07-24 to replace the
    old flat BREAKEVEN_PCT=52.4 constant used for spread/total edge
    calculations.

    52.4 was never actually a "fair" probability — it's the raw,
    vig-inclusive implied probability of a single -110 price. Once
    both sides of a real two-sided market are renormalized together
    (same no-vig approach already used for moneyline), a genuinely
    fair -110/-110 market comes out to exactly 50.0%, not 52.4%.
    Using 52.4 as if it were fair required the model to show slightly
    more edge than it should have before a spread/total pick could
    qualify — conservative-direction wrong, not aggressive, but wrong.

    Falls back to 50.0 if the odds are missing/invalid rather than
    crashing — same safe-default philosophy as get_market_implied()."""
    from services.odds_parser import american_to_implied
    try:
        p_picked = american_to_implied(picked_side_odds) * 100
        p_other = american_to_implied(other_side_odds) * 100
        total = p_picked + p_other
        if total <= 0:
            return 50.0
        return round(p_picked / total * 100, 1)
    except Exception:
        return 50.0


def _match_team_side(name: str, home: str, away: str) -> str | None:
    """Decides whether an odds-feed outcome name belongs to the home or
    away team. Exact match is tried first and wins outright — only when
    neither side matches exactly does this fall back to substring
    containment. Added 2026-09-02: plain `if home in name` / `elif away
    in name` silently misfiled real odds any time one team's name is a
    substring of the other's, which is common in CFB (Ohio/Ohio State,
    Texas/Texas A&M, Michigan/Michigan State, Washington/Washington
    State, ...). For an "Ohio State" outcome with home="Ohio", the old
    code matched home first (`"ohio" in "ohio state"`) and never let
    away get a chance — both outcomes ended up filed under home, away's
    list stayed empty, and the whole game silently fell back to a fake
    50/50 with no real price at all."""
    name_l, home_l, away_l = name.lower(), home.lower(), away.lower()
    if name_l == home_l:
        return "home"
    if name_l == away_l:
        return "away"
    home_hit = home_l in name_l
    away_hit = away_l in name_l
    if home_hit and not away_hit:
        return "home"
    if away_hit and not home_hit:
        return "away"
    return None


def get_market_implied(events_odds: list, home: str, away: str) -> tuple:
    """Returns (implied_home_pct, implied_away_pct, real_home_odds, real_away_odds).
    implied_*_pct are NO-VIG (fair) probabilities, renormalized to sum to
    100%. real_*_odds are the actual American price pulled from the odds
    feed — None if no real h2h odds were found for this game (caller
    should fall back to a synthesized price in that case, not treat None
    as a real -110)."""
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
                    name = (o.get("name") or "")
                    if abs(price) > 2000:
                        continue
                    prob = round(american_to_implied(price) * 100, 1)
                    side = _match_team_side(name, home, away)
                    if side == "home":
                        home_pairs.append((prob, price))
                    elif side == "away":
                        away_pairs.append((prob, price))
    if not home_pairs or not away_pairs:
        return 50.0, 50.0, None, None
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
                        name = (o.get("name") or "")
                        price = o.get("price", -110)
                        point = o.get("point")
                        side = _match_team_side(name, home, away)
                        if side == "home":
                            if out["spread_line"] is None:
                                out["spread_line"] = point
                            out["home_spread_odds"] = price
                        elif side == "away":
                            out["away_spread_odds"] = price
                elif key == "totals":
                    for o in market.get("outcomes", []):
                        name = (o.get("name") or "")
                        price = o.get("price", -110)
                        point = o.get("point")
                        # Guard against garbage/placeholder odds-feed
                        # entries with point<=0 — a real total line is
                        # never 0 or negative for any sport this
                        # platform covers.
                        if point is not None and point <= 0:
                            point = None
                        if name == "Over":
                            if out["total_line"] is None:
                                out["total_line"] = point
                            out["over_odds"] = price
                        elif name == "Under":
                            out["under_odds"] = price
        return out
    return out


def _build_bets_for_game(home: str, away: str, pred, events_odds: list, min_edge: float) -> tuple:
    """Turns one CFBPrediction into up to 3 bet dicts — moneyline, spread,
    total — instead of the old single moneyline-only dict. Spread/total
    are only included when a real posted line exists AND the model's edge
    clears min_edge, same bar moneyline uses. Shared by /edges and
    /predictions so both stay in sync (previously duplicated verbatim)."""
    from calibration_transform import apply_calibration

    # Apply the fitted calibration curve BEFORE any edge gets computed.
    # Same fix already wired into routes_nfl.py/routes_wnba.py — this route
    # never had it at all. NFL/CFB have zero graded picks right now (season
    # hasn't started), so apply_calibration() safely passes probabilities
    # through unchanged until enough real data accumulates to fit a curve.
    pred.home_win_prob = apply_calibration(pred.home_win_prob, "moneyline", sport="cfb") * 100
    pred.away_win_prob = apply_calibration(pred.away_win_prob, "moneyline", sport="cfb") * 100
    pred.home_cover_prob = apply_calibration(pred.home_cover_prob, "spread", sport="cfb") * 100
    pred.away_cover_prob = apply_calibration(pred.away_cover_prob, "spread", sport="cfb") * 100
    pred.over_prob = apply_calibration(pred.over_prob, "total", sport="cfb") * 100
    pred.under_prob = apply_calibration(pred.under_prob, "total", sport="cfb") * 100

    implied_home, implied_away, real_odds_home, real_odds_away = get_market_implied(events_odds, home, away)
    market = _get_market_details(events_odds, home, away)

    edge_home = pred.home_win_prob - implied_home
    edge_away = pred.away_win_prob - implied_away
    best_edge = max(edge_home, edge_away)
    label = f"{away} @ {home}"
    pred_margin = round(pred.projected_home - pred.projected_away, 1)

    # Sanity gate: the market's own implied home margin is -spread_line
    # (spread_line is home's own number, negative when favored — same
    # convention as the cover-probability fix elsewhere in this file), so
    # pred_margin + spread_line is exactly how far apart the model and the
    # market are on who wins by how much. A model that disagrees with a
    # real posted line by three touchdowns isn't finding an edge — with no
    # real defense/SOS signal for this year yet (see cfb_predictor.py's
    # market_spread blend), a gap this big means the model is working off
    # bad or stale inputs for one of these two teams, not that it knows
    # something Vegas doesn't. Only checked when a real line exists —
    # nothing to sanity-check a projection against otherwise.
    sanity_ok = True
    if market["spread_line"] is not None:
        disagreement = abs(pred_margin + market["spread_line"])
        if disagreement > 17:
            sanity_ok = False
            print(f"[CFB sanity gate] {label}: suppressing moneyline/spread — "
                  f"model margin {pred_margin:+.1f} vs market spread {market['spread_line']:+.1f} "
                  f"disagree by {disagreement:.1f} pts (> 17)")

    def synth_odds(prob):
        # Fallback ONLY — used when no real h2h odds exist for this game
        # in the feed. Fair odds derived from the model's own probability.
        # This is a synthesized display price, not a real market quote —
        # every bet dict carries odds_is_real so callers can tell which
        # kind of price they're looking at.
        return round(-(prob / (100 - prob)) * 100) if prob >= 50 else round(((100 - prob) / prob) * 100)

    bets = []

    # ---- Moneyline ----
    ml_pick = home if edge_home >= edge_away else away
    ml_prob = pred.home_win_prob if edge_home >= edge_away else pred.away_win_prob
    ml_implied = implied_home if edge_home >= edge_away else implied_away
    real_odds_for_pick = real_odds_home if edge_home >= edge_away else real_odds_away

    if real_odds_for_pick is not None:
        ml_odds = real_odds_for_pick
        odds_is_real = True
    else:
        ml_odds = synth_odds(ml_prob)
        odds_is_real = False

    # Gated by min_edge same as spread/total below — this used to append
    # unconditionally, so a moneyline pick with edge under the floor (even
    # negative) still rode into `results` whenever the SAME GAME also had
    # a qualifying spread or total bet (the outer len(bets)==1 check in
    # cfb_edges()/cfb_predictions() only caught the case where moneyline
    # was the game's only bet).
    #
    # Also gated on odds_is_real: a synthesized price is fair odds derived
    # FROM model_prob, so "edge" against it is circular — it can never mean
    # anything but "the model agrees with itself." No real sportsbook price
    # means no real edge to act on, so it's never worth emitting regardless
    # of how large that circular edge looks. Common for CFB blowout/G5 buy
    # games where the odds feed either has no h2h market at all or only
    # posts a price so extreme it fails the sanity filter in
    # get_market_implied() (e.g. -100000/+5000).
    if best_edge >= min_edge and odds_is_real and sanity_ok:
        bets.append({
            "game": label, "market": "moneyline",
            "bet": f"{ml_pick} ML", "pick": ml_pick, "line": None,
            "model_prob": ml_prob, "implied_prob": ml_implied,
            "edge": round(best_edge / 100, 4), "odds": ml_odds, "odds_is_real": odds_is_real,
            "projected": f"{pred.projected_home}-{pred.projected_away}",
            "projected_home": pred.projected_home, "projected_away": pred.projected_away,
            "projected_margin": pred_margin, "projected_total": pred.projected_total,
            "home_record": pred.home_record, "away_record": pred.away_record,
            "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
        })

    # ---- Spread ----
    if market["spread_line"] is not None:
        # Pick whichever side actually has the higher cover probability
        # against the real spread line — same pattern moneyline (edge_home
        # vs edge_away) and total (over_edge_pct vs under_edge_pct) already
        # use below. This used to be `pred_margin > 0`, which only reflects
        # who's projected to win outright and disagrees with cover_prob
        # any time the spread line isn't ~0 (a big favorite projected to
        # win by a little was picked to cover instead of the underdog).
        home_favored_to_cover = pred.home_cover_prob >= pred.away_cover_prob
        spread_pick = home if home_favored_to_cover else away
        spread_line_for_pick = market["spread_line"] if home_favored_to_cover else -market["spread_line"]
        spread_prob = pred.home_cover_prob if home_favored_to_cover else pred.away_cover_prob
        spread_odds = market["home_spread_odds"] if home_favored_to_cover else market["away_spread_odds"]
        other_spread_odds = market["away_spread_odds"] if home_favored_to_cover else market["home_spread_odds"]
        # Real fair (no-vig) probability from both sides of the spread
        # market, replacing the old flat BREAKEVEN_PCT=52.4 constant —
        # see _fair_two_way_prob()'s docstring for why 52.4 was never
        # actually a fair probability to begin with.
        spread_implied_pct = _fair_two_way_prob(spread_odds, other_spread_odds)
        spread_edge_pct = spread_prob - spread_implied_pct
        # Direct cap on spread_prob itself, separate from the margin-
        # disagreement sanity gate above. That gate only bounds how far
        # apart the model and market are on the MARGIN — it doesn't bound
        # the resulting cover PROBABILITY, since that also depends on
        # SCORE_STD_DEV. A 17-point disagreement can still simulate out to
        # a near-certain cover prob (confirmed: Ohio State -50.5 vs a
        # blended model margin of +33.5 is exactly a 17.0pt disagreement —
        # right at, not over, the gate's threshold — yet still simulates
        # to 88% for Ball State covering). No model here has enough real
        # signal this season to justify claiming near-certainty on a
        # spread; 85% is that ceiling.
        if spread_edge_pct >= min_edge and sanity_ok and spread_prob <= 85:
            sign = "+" if spread_line_for_pick > 0 else ""
            bets.append({
                "game": label, "market": "spread",
                "bet": f"{spread_pick} {sign}{spread_line_for_pick}",
                "pick": spread_pick, "line": spread_line_for_pick,
                "model_prob": spread_prob, "implied_prob": spread_implied_pct,
                "edge": round(spread_edge_pct / 100, 4), "odds": spread_odds,
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "projected_home": pred.projected_home, "projected_away": pred.projected_away,
                "projected_margin": pred_margin, "projected_total": pred.projected_total,
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            })

    # ---- Total ----
    if market["total_line"] is not None:
        # Real fair (no-vig) probability from both sides of the total
        # market, replacing the old flat BREAKEVEN_PCT=52.4 constant.
        over_implied_pct = _fair_two_way_prob(market["over_odds"], market["under_odds"])
        under_implied_pct = round(100 - over_implied_pct, 1)
        over_edge_pct = pred.over_prob - over_implied_pct
        under_edge_pct = pred.under_prob - under_implied_pct
        if max(over_edge_pct, under_edge_pct) >= min_edge:
            total_pick = "Over" if over_edge_pct >= under_edge_pct else "Under"
            total_prob = pred.over_prob if total_pick == "Over" else pred.under_prob
            total_odds = market["over_odds"] if total_pick == "Over" else market["under_odds"]
            total_implied_pct = over_implied_pct if total_pick == "Over" else under_implied_pct
            total_edge_pct = max(over_edge_pct, under_edge_pct)
            bets.append({
                "game": label, "market": "total",
                "bet": f"{total_pick} {market['total_line']}",
                "pick": total_pick, "line": market["total_line"],
                "model_prob": total_prob, "implied_prob": total_implied_pct,
                "edge": round(total_edge_pct / 100, 4), "odds": total_odds,
                "projected": f"{pred.projected_home}-{pred.projected_away}",
                "projected_home": pred.projected_home, "projected_away": pred.projected_away,
                "projected_margin": pred_margin, "projected_total": pred.projected_total,
                "home_record": pred.home_record, "away_record": pred.away_record,
                "home_rest": pred.home_rest_days, "away_rest": pred.away_rest_days,
            })

    return bets, best_edge


@router.get("/edges")
def cfb_edges(simulations: int = Query(default=50000), min_edge: float = Query(default=3.0)):
    from cfb_data import get_team_stats, FBS_TEAM_IDS, get_cfb_events
    from cfb_predictor import CFBPredictionEngine
    from services.odds_parser import get_live_odds
    engine = CFBPredictionEngine()
    events = get_cfb_events()
    events_odds = get_live_odds("ncaaf")
    results = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home not in FBS_TEAM_IDS or away not in FBS_TEAM_IDS:
            continue
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        market = _get_market_details(events_odds, home, away)
        spread_line = market["spread_line"] if market["spread_line"] is not None else 0.0
        over_under = market["total_line"] if market["total_line"] is not None else DEFAULT_TOTAL
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, spread_line=spread_line, over_under=over_under, simulations=simulations, market_spread=market["spread_line"])

        # min_edge is now enforced per-market inside _build_bets_for_game
        # (moneyline included, as of 2026-09-02) so an empty `bets` here
        # already means nothing in this game cleared the floor.
        bets, best_edge = _build_bets_for_game(home, away, pred, events_odds, min_edge)
        if not bets:
            continue
        results.extend(bets)
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}


@router.get("/preview")
def cfb_preview(home: str, away: str, simulations: int = Query(default=50000)):
    from cfb_data import get_team_stats, FBS_TEAM_IDS
    from cfb_predictor import CFBPredictionEngine
    if home not in FBS_TEAM_IDS or away not in FBS_TEAM_IDS:
        return {"error": f"Unknown team. Available: {list(FBS_TEAM_IDS.keys())}"}
    home_stats = get_team_stats(home)
    away_stats = get_team_stats(away)
    if not home_stats or not away_stats:
        return {"error": "Could not fetch team stats from ESPN"}
    engine = CFBPredictionEngine()
    pred = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=simulations)
    return {"prediction": pred.to_dict()}


@router.get("/predictions")
def cfb_predictions(simulations: int = Query(default=50000), min_edge: float = Query(default=0.0)):
    """Same multi-market build as /edges, but min_edge defaults to 0.0 —
    this endpoint shows ALL games regardless of edge (used for morning
    briefings), same convention now shared with routes_wnba.py."""
    from cfb_data import get_team_stats, FBS_TEAM_IDS, get_cfb_events
    from cfb_predictor import CFBPredictionEngine
    from services.odds_parser import get_live_odds
    engine = CFBPredictionEngine()
    events = get_cfb_events()
    events_odds = get_live_odds("ncaaf")
    results = []
    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        if home not in FBS_TEAM_IDS or away not in FBS_TEAM_IDS:
            continue
        home_stats = get_team_stats(home)
        away_stats = get_team_stats(away)
        if not home_stats or not away_stats:
            continue
        market = _get_market_details(events_odds, home, away)
        spread_line = market["spread_line"] if market["spread_line"] is not None else 0.0
        over_under = market["total_line"] if market["total_line"] is not None else DEFAULT_TOTAL
        pred = engine.predict(home_stats=home_stats, away_stats=away_stats, spread_line=spread_line, over_under=over_under, simulations=simulations, market_spread=market["spread_line"])

        bets, _ = _build_bets_for_game(home, away, pred, events_odds, min_edge)
        results.extend(bets)
    results.sort(key=lambda x: x["edge"], reverse=True)
    return {"count": len(results), "best_bets": results}
