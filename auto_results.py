"""
auto_results.py — Culture & Pulse Analytics
============================================
Scores yesterday's predictions against ESPN final scores, across ALL sports.
Populates the results table so recap scripts have data to report.

Usage:
    python auto_results.py yesterday             # score yesterday, all sports
    python auto_results.py yesterday --sport nfl # score just one sport
    python auto_results.py 2026-06-28
    python auto_results.py --dry-run
"""

import os
import re
import sys
import requests
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from elo_ratings import update_elo, is_exhibition_team

CENTRAL_OFFSET = -5

# One entry per sport. Add a new sport here and auto_results.py picks it up
# automatically — no other code changes needed.
SPORT_CONFIG = {
    "wnba": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "cfb": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    "ncaab": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
    "mlb": "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.espn.com/",
    "Origin": "https://www.espn.com",
}

# How many days forward a postponed/rained-out game might get made up.
# Doubleheader makeups are usually next-day, but a rainout can also get
# tacked onto the next scheduled series (up to ~1-2 weeks later in some
# cases). 10 covers the realistic range without scanning forever.
MAKEUP_WINDOW_DAYS = 10

# How far back to keep retrying predictions that never got a result.
# A prediction older than this is treated as a lost cause (bad data,
# team names that will never match, etc.) rather than retried forever.
STALE_LOOKBACK_DAYS = 14


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def parse_target_date(arg: str):
    if arg == "yesterday":
        return (get_today_ct() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        datetime.strptime(arg, "%Y-%m-%d")
        return arg
    except ValueError:
        print(f"Invalid date: {arg}. Use 'yesterday' or YYYY-MM-DD.")
        sys.exit(1)


def fetch_espn_results(date_str: str, sport: str) -> list:
    """
    Returns list of completed games with scores from ESPN for one sport.
    Each item: {game_id, home_team, away_team, home_score, away_score,
    actual_winner, start_time}. start_time (added 2026-07-24) is the
    raw ESPN event date string — needed to chronologically order
    doubleheader games, since two DH games share identical team names
    and only differ by start time. game_id is ESPN's numeric event id
    — captured here but not yet stored in the predictions/results
    tables (that's Phase 2 of the unification).
    """
    base_url = SPORT_CONFIG.get(sport)
    if not base_url:
        print(f"  No ESPN endpoint configured for sport '{sport}' — skipping.")
        return []

    date_fmt = date_str.replace("-", "")
    url = f"{base_url}?dates={date_fmt}"
    games = []

    scraperapi_key = os.environ.get("SCRAPERAPI_KEY", "").strip()
    fetch_url = (
        f"http://api.scraperapi.com?api_key={scraperapi_key}&url={url}"
        if scraperapi_key else url
    )

    try:
        r = requests.get(fetch_url, headers=HEADERS, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            print(f"  ESPN blocked/empty ({sport}): status={r.status_code} "
                  f"len={len(r.text)} body_start={r.text[:150]!r}")
            return games
        data = r.json()
    except Exception as e:
        print(f"  ESPN fetch error ({sport}): {e}")
        return games

    for event in data.get("events", []):
        completed = event.get("status", {}).get("type", {}).get("completed", False)
        if not completed:
            continue

        comps = event.get("competitions", [{}])
        competitors = comps[0].get("competitors", []) if comps else []
        home = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away = next((c for c in competitors if c.get("homeAway") == "away"), {})

        home_name = home.get("team", {}).get("displayName", "")
        away_name = away.get("team", {}).get("displayName", "")
        home_score = int(home.get("score", 0) or 0)
        away_score = int(away.get("score", 0) or 0)

        if not home_name or not away_name:
            continue

        actual_winner = home_name if home_score > away_score else away_name

        games.append({
            "game_id": event.get("id"),
            "home_team": home_name,
            "away_team": away_name,
            "home_score": home_score,
            "away_score": away_score,
            "actual_winner": actual_winner,
            "start_time": event.get("date", ""),
        })

        print(f"  [{sport.upper()}] ESPN: {away_name} @ {home_name} -> "
              f"{away_score}-{home_score} ({actual_winner} wins)")

    return games


def fetch_predictions(conn, date_str: str, sport: str) -> list:
    c = conn.cursor()
    c.execute("""
        SELECT * FROM predictions
        WHERE date = ? AND sport = ?
    """, (date_str, sport))
    return [dict(r) for r in c.fetchall()]


def _parse_dh_game_number(game_label: str):
    """Extracts the doubleheader game number from a prediction's game
    label, e.g. 'Pittsburgh Pirates @ Cleveland Guardians (DH Game 2)'
    -> 2. This suffix is added by routes_mlb.py's mlb_edges() for real
    MLB doubleheaders (see its dh_game_number_by_index logic). Returns
    None for a normal (non-DH) game label."""
    m = re.search(r"\(DH Game (\d+)\)", game_label or "")
    return int(m.group(1)) if m else None


def match_game(prediction: dict, espn_games: list):
    """Match a prediction to an ESPN result by team name.

    FIXED 2026-07-24: doubleheaders were silently mismatched before
    this. Two games between the same two teams on the same date have
    IDENTICAL home_team/away_team — this used to just return whichever
    ESPN game happened to come first in the list, so a prediction
    explicitly logged as "(DH Game 2)" could get scored against Game
    1's actual result instead of its own. Predictions for MLB
    doubleheaders already carry that "(DH Game N)" marker in their
    game label (see routes_mlb.py) — this now collects every
    team-name match as a candidate, sorts them chronologically by
    start_time, and picks the Nth one when a DH marker is present.
    Non-doubleheader games are unaffected (only one candidate either
    way); an out-of-range or missing DH number falls back to the
    earliest game, the same behavior this function always had."""
    pred_home = prediction.get("home_team", "")
    pred_away = prediction.get("away_team", "")

    candidates = [
        g for g in espn_games
        if (pred_home.lower() in g["home_team"].lower() or g["home_team"].lower() in pred_home.lower())
        and (pred_away.lower() in g["away_team"].lower() or g["away_team"].lower() in pred_away.lower())
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    candidates.sort(key=lambda g: g.get("start_time", ""))
    dh_game_number = _parse_dh_game_number(prediction.get("game", ""))
    if dh_game_number is not None and 1 <= dh_game_number <= len(candidates):
        return candidates[dh_game_number - 1]

    return candidates[0]


def score_prediction(prediction: dict, espn_game: dict) -> dict:
    """Determine if the prediction was correct.

    FIXED 2026-07-23: this function used to only know how to grade
    moneyline picks — it stripped " ML"/" ml" off the bet string and
    checked if what remained matched a team name. That's meaningless
    for a total pick like "Over 164.5" (no team name in the string at
    all), so every single total pick was silently marked WRONG
    regardless of the real outcome — confirmed via
    calibration_audit.py's --by-market breakdown showing an impossible
    0.0% actual win rate on totals. Spread bets partially "worked" by
    accident (the team name substring inside "Team +3.5" often matched
    the actual game winner), but that was grading "did the favorite
    win outright," a different and wrong question from "did they
    cover the spread."

    Now branches on prediction["market"] and uses the real posted
    pick/line fields already stored on the prediction row (the same
    fields _build_bets_for_game() writes — "pick" and "line") instead
    of re-parsing the display string. ASSUMES the predictions table
    actually has pick/line columns populated for spread/total rows —
    if they come back None for every row, log_prediction()'s column
    mapping needs checking, not this grading logic.

    KNOWN LIMITATION not fixed here: an exact push (margin+line == 0,
    or actual_total == line) is scored as a loss (correct=0), not a
    push/no-action. Real sportsbooks refund the stake on a push — this
    would need a third result state (not just 0/1) to handle properly,
    a bigger change than this grading fix. Flagged, not silently
    wrong-by-omission.
    """
    market = prediction.get("market", "moneyline")
    home_score = espn_game["home_score"]
    away_score = espn_game["away_score"]
    actual_winner = espn_game["actual_winner"]

    if market == "total":
        # pick is "Over" or "Under", line is the posted total.
        pick = (prediction.get("pick") or "").strip().lower()
        line = prediction.get("line")
        actual_total = home_score + away_score
        if line is None or pick not in ("over", "under"):
            correct = 0  # can't grade without a real line/pick — treated as wrong, not silently skipped
        elif pick == "over":
            correct = 1 if actual_total > line else 0
        else:
            correct = 1 if actual_total < line else 0

    elif market == "spread":
        # pick is the team name, line is THAT team's own posted number,
        # already sign-adjusted for whichever side was picked (see
        # _build_bets_for_game()'s spread_line_for_pick upstream).
        pick = (prediction.get("pick") or "").strip()
        line = prediction.get("line")
        home_team = espn_game["home_team"]
        if line is None or not pick:
            correct = 0
        else:
            pick_is_home = pick.lower() in home_team.lower() or home_team.lower() in pick.lower()
            margin = (home_score - away_score) if pick_is_home else (away_score - home_score)
            correct = 1 if margin + line > 0 else 0

    else:
        # moneyline — original logic, unchanged.
        bet = prediction.get("bet", "")
        picked_team = bet.replace(" ML", "").replace(" ml", "").strip()
        correct = 1 if picked_team.lower() in actual_winner.lower() or \
                       actual_winner.lower() in picked_team.lower() else 0

    return {
        "date": prediction["date"],
        "sport": prediction["sport"],
        "game": prediction["game"],
        "home_team": espn_game["home_team"],
        "away_team": espn_game["away_team"],
        "home_score": home_score,
        "away_score": away_score,
        "actual_winner": actual_winner,
        "prediction_id": prediction["id"],
        "correct": correct,
        "edge_at_pick": prediction.get("edge"),
        "odds_at_pick": prediction.get("odds"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def insert_result(conn, result: dict, dry_run: bool = False):
    if dry_run:
        status = "CORRECT" if result["correct"] == 1 else "WRONG"
        print(f"    [{result['sport'].upper()}] {status} -> {result['game']} -> {result['actual_winner']}")
        return

    sql = """
        INSERT INTO results (
            date, sport, game, home_team, away_team,
            home_score, away_score, actual_winner,
            prediction_id, correct, edge_at_pick, odds_at_pick, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(prediction_id) DO UPDATE SET
            home_score = excluded.home_score,
            away_score = excluded.away_score,
            actual_winner = excluded.actual_winner,
            correct = excluded.correct,
            edge_at_pick = excluded.edge_at_pick,
            odds_at_pick = excluded.odds_at_pick,
            updated_at = excluded.updated_at
    """
    params = (
        result["date"], result["sport"], result["game"],
        result["home_team"], result["away_team"],
        result["home_score"], result["away_score"], result["actual_winner"],
        result["prediction_id"], result["correct"],
        result["edge_at_pick"], result["odds_at_pick"], result["updated_at"],
    )
    conn.execute(sql, params)
    conn.commit()
    status = "CORRECT" if result["correct"] == 1 else "WRONG"
    print(f"    [{result['sport'].upper()}] {status} -> {result['game']} -> {result['actual_winner']} (saved)")

    # Keep Elo current as real results come in — added 2026-07-11.
    # Previously elo_ratings.py only updated via manual `backfill`,
    # which pulled from head_to_head (confirmed missing from
    # production entirely — check_head_to_head_freshness.py). This is
    # now the live feed that keeps elo_ratings from going stale again.
    if not is_exhibition_team(result["home_team"]) and not is_exhibition_team(result["away_team"]):
        try:
            update_elo(
                result["sport"], result["home_team"], result["away_team"],
                result["home_score"], result["away_score"], date=result["date"]
            )
        except Exception as e:
            # Elo failing to update should never block a results write —
            # results is the source of truth; Elo can be rebacked via
            # `python elo_ratings.py backfill <sport>` if this ever fires.
            print(f"    ⚠️  Elo update failed for {result['game']}: {e}")


def score_prop_results(conn, date_str: str, dry_run: bool = False):
    """
    WNBA-only for now — props only exist for WNBA. Unchanged placeholder
    from the original file; full scoring pending a prop-result tracking table.
    """
    c = conn.cursor()
    c.execute("""
        SELECT * FROM player_props
        WHERE date = ? AND sport = 'wnba'
    """, (date_str,))
    props = [dict(r) for r in c.fetchall()]

    if not props:
        return
    print(f"\n  {len(props)} WNBA prop(s) logged (result tracking table pending).")


def score_sport(conn, date_str: str, sport: str, dry_run: bool = False):
    """Score one sport for one date. Returns (scored_count, prediction_count)."""
    print(f"\n--- {sport.upper()} ---")
    espn_games = fetch_espn_results(date_str, sport)
    print(f"  Found {len(espn_games)} completed game(s)")

    predictions = fetch_predictions(conn, date_str, sport)
    print(f"  Found {len(predictions)} prediction(s) logged")

    if not predictions:
        return 0, 0

    scored = 0
    nearby_cache = {}  # date_str -> espn_games, avoids refetching the
                        # same nearby date for every prediction below

    for pred in predictions:
        espn_game = match_game(pred, espn_games)

        # If no match on the exact date, check the day before (ESPN
        # sometimes logs a late game under a different calendar date)
        # and forward across MAKEUP_WINDOW_DAYS — this is the case that
        # matters for postponed/rained-out games, which get replayed
        # anywhere from the next day to over a week later, often as
        # part of a later doubleheader. A postponed game never shows up
        # as "completed" on its original date, so without this forward
        # scan the prediction has no chance of matching within this run.
        if not espn_game:
            offsets = [-1] + list(range(1, MAKEUP_WINDOW_DAYS + 1))
            for offset in offsets:
                nearby_date = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")
                if nearby_date not in nearby_cache:
                    nearby_cache[nearby_date] = fetch_espn_results(nearby_date, sport)
                espn_game = match_game(pred, nearby_cache[nearby_date])
                if espn_game:
                    print(f"    Matched via {nearby_date} instead of {date_str} (makeup/postponement)")
                    break

        if not espn_game:
            print(f"    No ESPN match for: {pred.get('game')} — skipping (will retry on future runs)")
            continue
        result = score_prediction(pred, espn_game)
        insert_result(conn, result, dry_run=dry_run)
        scored += 1

    if sport == "wnba":
        score_prop_results(conn, date_str, dry_run=dry_run)

    return scored, len(predictions)


def rescan_unresolved_predictions(conn, sport: str, dry_run: bool = False):
    """Catches predictions from earlier runs that never got a result —
    almost always a postponed/rained-out game whose makeup hadn't been
    played yet the day this ran normally. Since the daily cron only
    ever scores 'yesterday' once, a game that's still postponed at that
    point never gets looked at again unless something re-checks it.

    This runs every day, for every sport, and re-attempts any
    prediction from the last STALE_LOOKBACK_DAYS days that still has
    no matching row in results — so a postponed game gets picked up
    automatically within a day or two of actually being played,
    instead of staying PENDING indefinitely.
    """
    c = conn.cursor()
    cutoff = (get_today_ct() - timedelta(days=STALE_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    c.execute("""
        SELECT p.* FROM predictions p
        LEFT JOIN results r ON r.prediction_id = p.id
        WHERE r.prediction_id IS NULL
          AND p.sport = ?
          AND p.date >= ?
    """, (sport, cutoff))
    stale = [dict(r) for r in c.fetchall()]
    if not stale:
        return 0

    print(f"\n--- {sport.upper()} rescan: {len(stale)} unresolved prediction(s) "
          f"from the last {STALE_LOOKBACK_DAYS} days ---")

    # Cache ESPN fetches per date within this rescan so N stale
    # predictions on the same date don't refetch the same scoreboard.
    espn_cache = {}
    rescanned = 0

    for pred in stale:
        pred_date = pred["date"]
        matched = None
        for offset in range(0, MAKEUP_WINDOW_DAYS + 1):
            check_date = (datetime.strptime(pred_date, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")
            if check_date not in espn_cache:
                espn_cache[check_date] = fetch_espn_results(check_date, sport)
            matched = match_game(pred, espn_cache[check_date])
            if matched:
                if offset > 0:
                    print(f"    Matched via {check_date} instead of {pred_date} (makeup/postponement)")
                break

        if not matched:
            continue

        result = score_prediction(pred, matched)
        insert_result(conn, result, dry_run=dry_run)
        rescanned += 1

    return rescanned


def run(date_str: str, sport_filter: str = None, dry_run: bool = False):
    print(f"Scoring predictions for {date_str}...")

    sports = [sport_filter] if sport_filter else list(SPORT_CONFIG.keys())

    conn = get_conn()
    totals = {}

    for sport in sports:
        scored, total = score_sport(conn, date_str, sport, dry_run=dry_run)
        if total:
            totals[sport] = (scored, total)

    # Always rescan for older unresolved predictions (postponements,
    # rainouts) regardless of what date was targeted above — this is
    # what actually stops picks from getting stuck PENDING forever.
    rescan_totals = {}
    for sport in sports:
        rescanned = rescan_unresolved_predictions(conn, sport, dry_run=dry_run)
        if rescanned:
            rescan_totals[sport] = rescanned

    conn.close()

    print(f"\n{'DRY RUN — ' if dry_run else ''}Summary for {date_str}:")
    if not totals and not rescan_totals:
        print("  No predictions found for this date, any sport.")
        return

    for sport, (scored, total) in totals.items():
        print(f"  {sport.upper()}: scored {scored}/{total}")

    if rescan_totals:
        print(f"\nResolved from rescan (postponements/makeups caught up):")
        for sport, n in rescan_totals.items():
            print(f"  {sport.upper()}: {n}")

    if not dry_run:
        conn2 = get_conn()
        c = conn2.cursor()
        for sport in totals:
            c.execute("""
                SELECT COUNT(*) as total, SUM(correct) as wins
                FROM results WHERE date = ? AND sport = ?
            """, (date_str, sport))
            row = c.fetchone()
            if row and row["total"]:
                losses = row["total"] - (row["wins"] or 0)
                print(f"  {sport.upper()} daily record: {row['wins'] or 0}-{losses}")
        conn2.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default="yesterday",
                         help="Date to score: 'yesterday' or YYYY-MM-DD")
    parser.add_argument("--sport", default=None,
                         help="Score only this sport (wnba, nfl, cfb, ncaab). Default: all.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Print results without writing to DB")
    args = parser.parse_args()

    target = parse_target_date(args.date)
    run(target, sport_filter=args.sport, dry_run=args.dry_run)