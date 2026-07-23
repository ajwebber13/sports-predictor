"""
routes_mlb.py
FastAPI routes for MLB predictions — mirrors routes_cfb.py / routes_nfl.py.

PREDICTION ENGINE v2 (2026-07-20): /edges now emits up to 3 bet rows per
game — moneyline, run line, total — instead of moneyline-only with
spread/total data tacked on as unused extra fields. See
_build_bets_for_pred() below.

Run-line and total bets use REAL odds via mlb_data.py's
get_run_line_odds()/get_total_odds() — both marked "not yet verified
against a live payload" in that file (built before an in-season game was
available to confirm ESPN's "pointSpread"/"total" keys match). Both
functions already return None safely if the keys don't match, so this
route falls back to -110 per-side automatically with no crash risk
either way — but the run-line/total odds shown won't be real prices
until that's confirmed against a live game. Worth a quick check now that
MLB is in season.
"""

from fastapi import APIRouter, Query
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from mlb_data import get_mlb_events, get_moneyline_odds, get_run_line_odds, get_total_odds, american_to_implied
from mlb_predictor import predict_game

# Games processed concurrently in mlb_edges() — bounded so we don't
# hammer ESPN/odds APIs with 15+ simultaneous requests on a big slate.
#
# LOWERED 6 -> 3 (2026-07-22): real timing data showed the first
# batch of 6 concurrent games taking 144-152s each in pass1 alone
# (vs 10-18s for games processed later, once earlier threads freed
# up) — classic request congestion from 6 threads all hitting ESPN/
# MLB Stats API at the exact same instant. Lowering concurrency
# smooths the initial burst at the cost of slightly longer total
# wall-clock time for a full slate. TUNABLE — raise back toward 6 if
# real runs show 3 leaves meaningful headroom; lower further if the
# first batch is still slow.
MLB_EDGES_MAX_WORKERS = 3

# Two-pass matchup filtering: a game must show at least
# (min_edge - CANDIDATE_BUFFER) on the cheap no-matchup pass before
# we spend the expensive roster+per-batter matchup fetch on it.
# 5.0 percentage points is a starting guess for how much matchup
# could realistically swing an edge — TUNABLE. If real results show
# matchup regularly flips games from below this buffer into
# qualifying, raise it; if refined games almost never move much,
# lower it to cut API load further.
MLB_MATCHUP_CANDIDATE_BUFFER = 5.0

router = APIRouter(prefix="/mlb", tags=["MLB"])

# Breakeven win% for standard -110 juice — same baseline WNBA/CFB/NFL use
# as the "no edge" floor for run-line/total picks, since those markets
# don't have a real book-implied probability wired in the way moneyline
# does via get_moneyline_odds().
BREAKEVEN_PCT = 52.4


def _build_bets_for_pred(pred: dict, game_label: str, ml_odds: dict, min_edge: float,
                          run_line_odds: dict = None, total_odds: dict = None) -> list:
    """Turns one predict_game() result into up to 3 bet dicts — moneyline,
    run line ("spread" market), total — instead of the old single
    moneyline dict with spread/total fields attached but unused. Each
    dict carries market/pick/line so database.log_prediction() can log
    it as its own row.

    Replaces the old _spread_and_total_fields() helper. Along the way,
    fixes a real bug in that helper: it always displayed the HOME team's
    run-line number in spread_pick regardless of which side the model
    actually favored to cover — e.g. it could say "Cubs -1.5" even when
    the model favored the away team. Pick and line are now derived
    together from the same favored side.
    """
    bets = []
    model_home = round(pred["home_win_prob"] * 100, 1)
    model_away = round(pred["away_win_prob"] * 100, 1)

    # Remove vig: implied_home/implied_away are converted from real odds
    # separately, so raw they sum to ~104-106% (the vig). Renormalize so
    # edge_home/edge_away compare model_prob against the fair (no-vig)
    # probability, not a vig-inflated one on both sides.
    raw_implied_home = american_to_implied(ml_odds["home"]) * 100
    raw_implied_away = american_to_implied(ml_odds["away"]) * 100
    total_implied = raw_implied_home + raw_implied_away
    implied_home = round(raw_implied_home / total_implied * 100, 1)
    implied_away = round(raw_implied_away / total_implied * 100, 1)
    edge_home = round(model_home - implied_home, 2)
    edge_away = round(model_away - implied_away, 2)
    projected = f"{pred['proj_home_runs']}-{pred['proj_away_runs']}"
    pred_margin = round(pred["proj_home_runs"] - pred["proj_away_runs"], 1)

    common = {
        "game": game_label,
        "projected": projected,
        "projected_home": pred["proj_home_runs"], "projected_away": pred["proj_away_runs"],
        "projected_margin": pred_margin,
        "home_record": pred.get("home_record", ""), "away_record": pred.get("away_record", ""),
        "home_injuries": pred.get("home_injuries", ""), "away_injuries": pred.get("away_injuries", ""),
        "home_rest": pred.get("home_rest"), "away_rest": pred.get("away_rest"),
    }

    # ---- Moneyline (both sides checked independently, same as before) ----
    if edge_home >= min_edge:
        bets.append({
            **common, "market": "moneyline",
            "bet": f"{pred['home_team']} ML", "pick": pred["home_team"], "line": None,
            "odds": ml_odds["home"], "model_prob": model_home, "implied_prob": implied_home,
            "edge": round(edge_home / 100, 4),
        })
    if edge_away >= min_edge:
        bets.append({
            **common, "market": "moneyline",
            "bet": f"{pred['away_team']} ML", "pick": pred["away_team"], "line": None,
            "odds": ml_odds["away"], "model_prob": model_away, "implied_prob": implied_away,
            "edge": round(edge_away / 100, 4),
        })

    # ---- Run line ("spread" market) ----
    posted_run_line = pred.get("posted_run_line")
    home_cover_prob = pred.get("home_cover_prob")
    away_cover_prob = pred.get("away_cover_prob")
    if posted_run_line is not None and home_cover_prob is not None:
        home_favored_to_cover = pred_margin > -posted_run_line
        rl_pick = pred["home_team"] if home_favored_to_cover else pred["away_team"]
        rl_line = posted_run_line if home_favored_to_cover else -posted_run_line
        rl_prob = home_cover_prob if home_favored_to_cover else away_cover_prob
        # FIXED 2026-07-21: edge was measured against a flat 52.4%
        # (BREAKEVEN_PCT, the -110 baseline) instead of the real fetched
        # odds' actual implied probability — inflating edge whenever the
        # real run-line price wasn't standard -110 juice (e.g. -191
        # implies ~65.6%, not 52.4%). Now computes implied_prob from the
        # real odds, same as moneyline already does via
        # american_to_implied().
        if run_line_odds:
            rl_odds = run_line_odds["home_odds"] if home_favored_to_cover else run_line_odds["away_odds"]
        else:
            rl_odds = -110  # get_run_line_odds() returned None for this game — fallback
        rl_implied_pct = round(american_to_implied(rl_odds) * 100, 1)
        rl_edge_pct = round(rl_prob - rl_implied_pct, 2)
        if rl_edge_pct >= min_edge:
            sign = "+" if rl_line > 0 else ""
            bets.append({
                **common, "market": "spread",
                "bet": f"{rl_pick} {sign}{rl_line}", "pick": rl_pick, "line": rl_line,
                "odds": rl_odds,
                "model_prob": rl_prob, "implied_prob": rl_implied_pct,
                "edge": round(rl_edge_pct / 100, 4),
            })

    # ---- Total ----
    posted_total = pred.get("posted_total")
    over_prob = pred.get("over_prob")
    under_prob = pred.get("under_prob")
    if posted_total is not None and over_prob is not None:
        # FIXED 2026-07-21: same BREAKEVEN_PCT bug as run line above —
        # over/under carry different real odds (and therefore different
        # true implied probabilities), so each needs its own implied_prob
        # computed from the actual fetched price, not a shared flat 52.4%.
        if total_odds:
            over_odds = total_odds["over_odds"]
            under_odds = total_odds["under_odds"]
        else:
            over_odds = -110  # get_total_odds() returned None for this game — fallback
            under_odds = -110
        over_implied_pct = round(american_to_implied(over_odds) * 100, 1)
        under_implied_pct = round(american_to_implied(under_odds) * 100, 1)
        over_edge_pct = round(over_prob - over_implied_pct, 2)
        under_edge_pct = round((under_prob if under_prob is not None else 0) - under_implied_pct, 2)
        if max(over_edge_pct, under_edge_pct) >= min_edge:
            total_pick = "Over" if over_edge_pct >= under_edge_pct else "Under"
            total_prob = over_prob if total_pick == "Over" else under_prob
            total_edge_pct = max(over_edge_pct, under_edge_pct)
            t_odds = over_odds if total_pick == "Over" else under_odds
            t_implied_pct = over_implied_pct if total_pick == "Over" else under_implied_pct
            bets.append({
                **common, "market": "total",
                "bet": f"{total_pick} {posted_total}", "pick": total_pick, "line": posted_total,
                "odds": t_odds,
                "model_prob": total_prob, "implied_prob": t_implied_pct,
                "edge": round(total_edge_pct / 100, 4),
            })

    return bets


@router.get("/predictions")
def mlb_predictions():
    """
    Returns ALL games with predictions, no edge filter — matches
    the WNBA/CFB/NFL /predictions route used by morning briefings.
    Left as the raw prediction payload (not bet rows) — unchanged.
    """
    events = get_mlb_events()
    results = []

    for event in events:
        pred = predict_game(event)
        results.append(pred)

    return {"count": len(results), "games": results}


def _process_one_game(event: dict, dh_game_number: int, matchup_is_dh: bool, min_edge: float) -> list:
    """All network-bound work for ONE game — predict + 3 odds calls.
    Pure function of its inputs (no shared mutable state), safe to run
    concurrently across games in a thread pool. Returns [] if no
    moneyline odds are available (same skip behavior as before).

    TWO-PASS matchup filtering (2026-07-22): first pass skips the
    expensive roster+per-batter matchup fetch entirely. Only games
    that clear a lowered "candidate" threshold get a second,
    matchup-included predict_game() call. This is the fix for MLB's
    /edges route timing out — matchup's per-game API call volume was
    the dominant remaining cost after weather/team-stats caching.

    TIMING instrumentation (2026-07-22): prints wall-clock time for
    each pass so Render's free-tier logs (no Memory/CPU metrics
    available) can show where time is actually going, since the
    route has been timing out with no visible cause.
    """
    t0 = time.time()
    odds = get_moneyline_odds(event)
    if not odds:
        return []

    run_line_odds = get_run_line_odds(event)
    total_odds = get_total_odds(event)

    # Pass 1: cheap, no matchup fetch at all
    pred = predict_game(event, include_matchup=False)
    game_label = f"{pred['away_team']} @ {pred['home_team']}"
    if matchup_is_dh:
        game_label += f" (DH Game {dh_game_number})"
    t1 = time.time()
    print(f"  [MLB TIMING] {game_label}: pass1 (no matchup) took {t1 - t0:.1f}s")

    candidate_edge = max(min_edge - MLB_MATCHUP_CANDIDATE_BUFFER, 0)
    candidate_bets = _build_bets_for_pred(pred, game_label, odds, candidate_edge,
                                           run_line_odds=run_line_odds, total_odds=total_odds)
    if not candidate_bets:
        print(f"  [MLB TIMING] {game_label}: not a candidate, skipping matchup fetch (total {t1 - t0:.1f}s)")
        return []  # not close enough to qualify even with matchup's help — skip the expensive fetch

    # Pass 2: this game is a real candidate — refine with matchup included
    print(f"  [MLB TIMING] {game_label}: IS a candidate, starting matchup fetch")
    pred = predict_game(event, include_matchup=True)
    t2 = time.time()
    print(f"  [MLB TIMING] {game_label}: pass2 (with matchup) took {t2 - t1:.1f}s (total {t2 - t0:.1f}s)")
    return _build_bets_for_pred(pred, game_label, odds, min_edge,
                                 run_line_odds=run_line_odds, total_odds=total_odds)


@router.get("/edges")
def mlb_edges(min_edge: float = Query(default=3.0)):
    request_start = time.time()
    events = get_mlb_events()
    print(f"[MLB TIMING] mlb_edges started, {len(events)} game(s) fetched at {time.time() - request_start:.1f}s")
    best_bets = []

    # Count how many times each matchup appears today — 2+ means doubleheader
    matchup_counts = Counter()
    for event in events:
        competitors = event["competitions"][0]["competitors"]
        home = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "home")
        away = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "away")
        matchup_counts[(home, away)] += 1

    # DH game numbers precomputed from list order BEFORE any network
    # calls or parallelization — pure, no shared mutable state touched
    # once the thread pool starts. Doubleheader Game 1/Game 2 labeling
    # stays correct regardless of which thread finishes first.
    dh_game_number_by_index = {}
    seen_counts = Counter()
    for i, event in enumerate(events):
        competitors = event["competitions"][0]["competitors"]
        home = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "home")
        away = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "away")
        matchup_key = (home, away)
        seen_counts[matchup_key] += 1
        dh_game_number_by_index[i] = seen_counts[matchup_key]

    with ThreadPoolExecutor(max_workers=MLB_EDGES_MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                _process_one_game,
                event,
                dh_game_number_by_index[i],
                matchup_counts[(
                    next(c["team"]["displayName"] for c in event["competitions"][0]["competitors"] if c["homeAway"] == "home"),
                    next(c["team"]["displayName"] for c in event["competitions"][0]["competitors"] if c["homeAway"] == "away"),
                )] > 1,
                min_edge,
            ): i
            for i, event in enumerate(events)
        }
        for future in as_completed(futures):
            try:
                best_bets.extend(future.result())
            except Exception as e:
                # One game's failure (bad ESPN payload, odds API hiccup,
                # etc.) no longer takes down the whole slate — matches
                # the existing "if not odds: continue" skip philosophy,
                # just extended to any per-game exception.
                print(f"mlb_edges: game processing error: {e}")

    best_bets.sort(key=lambda x: x["edge"], reverse=True)
    print(f"mlb_edges: {len(best_bets)} qualifying bet(s) from {len(events)} game(s) "
          f"(two-pass matchup filtering active, buffer={MLB_MATCHUP_CANDIDATE_BUFFER})")
    print(f"[MLB TIMING] mlb_edges TOTAL time: {time.time() - request_start:.1f}s")
    return {"count": len(best_bets), "best_bets": best_bets}


@router.get("/preview")
def mlb_preview():
    """
    Lightweight game list for morning briefing — team names and
    basic matchup info without full prediction payload.
    """
    events = get_mlb_events()
    preview = []
    for e in events:
        competitors = e["competitions"][0]["competitors"]
        home = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "home")
        away = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "away")
        preview.append({"home_team": home, "away_team": away})
    return {"count": len(preview), "games": preview}
