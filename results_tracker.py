"""
results_tracker.py — Culture & Pulse Analytics
Auto-pull version: fetches actual game results from ESPN
and updates prediction JSONs + results_log.json automatically.

Usage:
  python results_tracker.py           # auto-pull + report
  python results_tracker.py report    # report only
  python results_tracker.py reset     # clear results log
"""

import sys
import os
import json
import glob
import requests
from datetime import datetime, timedelta
from difflib import get_close_matches


# ─────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────

BASE_DIR        = os.path.dirname(__file__)
PREDICTIONS_DIR = os.path.join(BASE_DIR, "data", "predictions")
RESULTS_LOG     = os.path.join(BASE_DIR, "results_log.json")

# Version boundary dates — mirrors prediction_logger.py
# Update these whenever you bump CURRENT_MODEL_VERSION
VERSION_DATES = {
    "v1": ("2026-01-01", "2026-06-09"),   # basic Elo + power ratings
    "v2": ("2026-06-10", "2026-06-18"),   # + ensemble + injury + home/away + situational
    "v3": ("2026-06-19", "9999-12-31"),   # + Elo recalibration + CLV + HBCU (current)
}

VERSION_LABELS = {
    "v1": "v1  Basic Elo + Power Ratings      [retired]",
    "v2": "v2  Ensemble + Injury + Splits     [retired]",
    "v3": "v3  Elo + CLV + HBCU              [current]",
}


# ─────────────────────────────────────────────────────────────
# ESPN ENDPOINTS
# ─────────────────────────────────────────────────────────────

ESPN_ENDPOINTS = {
    "wnba":  "http://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    "nba":   "http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
    "nfl":   "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
    "ncaaf": "http://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard",
    "ncaab": "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard",
    "ncaaw": "http://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard",
}

ESPN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

_espn_cache: dict = {}


# ─────────────────────────────────────────────────────────────
# ESPN RESULT FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_espn_results(sport: str, date_str: str) -> list:
    cache_key = f"{sport}_{date_str}"
    if cache_key in _espn_cache:
        return _espn_cache[cache_key]

    endpoint = ESPN_ENDPOINTS.get(sport.lower())
    if not endpoint:
        return []

    espn_date = date_str.replace("-", "")

    try:
        r = requests.get(
            endpoint,
            params={"dates": espn_date},
            headers=ESPN_HEADERS,
            timeout=10,
        )
        if r.status_code != 200:
            return []

        data   = r.json()
        events = data.get("events", [])
        games  = []

        for event in events:
            competitions = event.get("competitions", [])
            if not competitions:
                continue

            comp        = competitions[0]
            competitors = comp.get("competitors", [])
            status      = comp.get("status", {}).get("type", {}).get("completed", False)

            if not status or len(competitors) < 2:
                continue

            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)

            if not home or not away:
                continue

            home_name  = home.get("team", {}).get("displayName", "")
            away_name  = away.get("team", {}).get("displayName", "")
            home_score = int(home.get("score", 0))
            away_score = int(away.get("score", 0))
            winner     = home_name if home_score > away_score else away_name

            games.append({
                "event_id":   event.get("id", ""),
                "home_team":  home_name,
                "away_team":  away_name,
                "home_score": home_score,
                "away_score": away_score,
                "winner":     winner,
            })

        _espn_cache[cache_key] = games
        return games

    except Exception as e:
        print(f"  ESPN fetch error ({sport} {date_str}): {e}")
        return []


def match_team_name(name: str, candidates: list) -> str:
    if not name or not candidates:
        return ""
    name_lower  = name.lower()
    cands_lower = [c.lower() for c in candidates]
    if name_lower in cands_lower:
        return candidates[cands_lower.index(name_lower)]
    matches = get_close_matches(name_lower, cands_lower, n=1, cutoff=0.75)
    if matches:
        return candidates[cands_lower.index(matches[0])]
    return ""


def find_actual_winner(sport: str, date_str: str, home_team: str, away_team: str, event_id: str = "") -> str:
    games = fetch_espn_results(sport, date_str)
    if not games:
        return ""

    if event_id:
        for g in games:
            if g.get("event_id") == event_id:
                return g["winner"]

    all_teams    = []
    for g in games:
        all_teams.extend([g["home_team"], g["away_team"]])

    matched_home = match_team_name(home_team, all_teams)
    matched_away = match_team_name(away_team, all_teams)

    for g in games:
        if (g["home_team"] == matched_home or g["away_team"] == matched_away or
                g["home_team"] == matched_away or g["away_team"] == matched_home):
            return g["winner"]

    return ""


# ─────────────────────────────────────────────────────────────
# VERSION HELPER
# ─────────────────────────────────────────────────────────────

def infer_version_from_date(date_str: str) -> str:
    """Infer model version from game date for results that predate version tagging."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        for version, (start, end) in VERSION_DATES.items():
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end, "%Y-%m-%d").date()
            if s <= d <= e:
                return version
    except Exception:
        pass
    return "v1"


# ─────────────────────────────────────────────────────────────
# STORAGE HELPERS
# ─────────────────────────────────────────────────────────────

def load_results() -> list:
    if not os.path.exists(RESULTS_LOG):
        return []
    with open(RESULTS_LOG, "r") as f:
        return json.load(f)


def save_results(results: list):
    with open(RESULTS_LOG, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Saved {len(results)} results to results_log.json")


def result_exists(game: str, date_str: str, results: list) -> bool:
    return any(r["game"] == game and r["date"] == date_str for r in results)


# ─────────────────────────────────────────────────────────────
# AUTO-PULL AND LOG
# ─────────────────────────────────────────────────────────────

def auto_pull_results(results: list) -> list:
    pattern = os.path.join(PREDICTIONS_DIR, "*.json")
    files   = sorted(glob.glob(pattern))

    if not files:
        print("\n  No prediction files found in data/predictions/")
        return results

    print(f"\n  Scanning {len(files)} prediction file(s)...\n")

    new_count = 0
    pending   = 0
    not_found = 0
    today     = datetime.now().date()

    for filepath in files:
        with open(filepath, "r") as f:
            try:
                pred = json.load(f)
            except Exception:
                continue

        game           = pred.get("game", "")
        sport          = pred.get("sport", "").lower()
        date_str       = pred.get("date", "")
        bet_label      = pred.get("bet", "")
        model_prob     = pred.get("model_prob", 50)
        edge           = pred.get("edge", 0)
        odds           = pred.get("odds", "N/A")
        event_id       = pred.get("event_id", "")
        model_version  = pred.get("model_version") or infer_version_from_date(date_str)

        actual_winner = pred.get("actual_result", {}).get("actual_winner", "")
        if actual_winner:
            if not result_exists(game, date_str, results):
                parts            = game.split(" @ ")
                away_team        = parts[0] if len(parts) == 2 else ""
                home_team        = parts[1] if len(parts) == 2 else ""
                bet_on_home      = home_team in bet_label
                predicted_winner = home_team if bet_on_home else away_team
                won = (predicted_winner.lower() in actual_winner.lower() or
                       actual_winner.lower() in predicted_winner.lower())
                _append_result(results, pred, game, sport, date_str, bet_label,
                               odds, model_prob, edge, actual_winner, won, model_version)
                new_count += 1
            continue

        try:
            game_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if game_date >= today:
                pending += 1
                continue
        except Exception:
            pass

        parts     = game.split(" @ ")
        away_team = parts[0] if len(parts) == 2 else ""
        home_team = parts[1] if len(parts) == 2 else ""

        if not sport or not date_str or not home_team:
            not_found += 1
            continue

        winner = find_actual_winner(sport, date_str, home_team, away_team, event_id)

        if not winner:
            print(f"  ⚠  No ESPN result: {game} ({date_str})")
            not_found += 1
            continue

        pred["actual_result"]["actual_winner"] = winner
        with open(filepath, "w") as f:
            json.dump(pred, f, indent=2)

        parts            = game.split(" @ ")
        away_team        = parts[0] if len(parts) == 2 else ""
        home_team        = parts[1] if len(parts) == 2 else ""
        bet_on_home      = home_team in bet_label
        predicted_winner = home_team if bet_on_home else away_team
        won = (predicted_winner.lower() in winner.lower() or
               winner.lower() in predicted_winner.lower())
        result_str = "✅ WIN" if won else "❌ LOSS"

        print(f"  {result_str}  {game}  |  Bet: {bet_label}  |  Winner: {winner}")

        if not result_exists(game, date_str, results):
            _append_result(results, pred, game, sport, date_str, bet_label,
                           odds, model_prob, edge, winner, won, model_version)
            new_count += 1

    print(f"\n  {new_count} new result(s) logged.")
    if pending:
        print(f"  {pending} game(s) pending (future dates).")
    if not_found:
        print(f"  {not_found} game(s) not found on ESPN yet.")

    return results


def _append_result(results, pred, game, sport, date_str, bet_label,
                   odds, model_prob, edge, actual_winner, won, model_version="v1"):
    results.append({
        "game":          game,
        "sport":         sport.upper(),
        "date":          date_str,
        "event_id":      pred.get("event_id", ""),
        "model_version": model_version,
        "bet":           bet_label,
        "odds":          odds,
        "model_prob":    model_prob,
        "edge":          edge,
        "actual_winner": actual_winner,
        "won":           won,
        "logged_at":     datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


# ─────────────────────────────────────────────────────────────
# ROI / UNITS CALCULATOR
# ─────────────────────────────────────────────────────────────

def parse_odds(odds_str) -> float:
    """
    Convert American odds string to decimal multiplier.
    Returns None if unparseable.
    Examples: '-110' → 0.909, '+150' → 1.5, 'N/A' → None
    """
    try:
        odds = int(str(odds_str).replace(" ", ""))
        if odds > 0:
            return odds / 100.0
        else:
            return 100.0 / abs(odds)
    except Exception:
        return None


def calc_roi(results: list) -> dict:
    """
    Calculate units won/lost and ROI assuming 1 unit flat bet per pick.
    Uses American odds from each result. Falls back to -110 if missing.
    Returns dict with units_won, units_lost, net_units, roi_pct, bets_with_odds.
    """
    DEFAULT_ODDS_RETURN = 100 / 110  # -110 juice standard

    net_units      = 0.0
    bets_with_odds = 0
    bets_no_odds   = 0

    for r in results:
        odds_raw   = r.get("odds", "N/A")
        multiplier = parse_odds(odds_raw)

        if multiplier is None:
            multiplier   = DEFAULT_ODDS_RETURN
            bets_no_odds += 1
        else:
            bets_with_odds += 1

        if r["won"]:
            net_units += multiplier       # win: collect payout
        else:
            net_units -= 1.0              # loss: lose 1 unit staked

    total    = len(results)
    roi_pct  = (net_units / total * 100) if total > 0 else 0

    return {
        "net_units":      round(net_units, 2),
        "roi_pct":        round(roi_pct, 2),
        "bets_with_odds": bets_with_odds,
        "bets_no_odds":   bets_no_odds,
        "total":          total,
    }


def format_roi_block(results: list, label: str = "") -> str:
    """Return a formatted ROI block string for a result set."""
    if not results:
        return ""

    roi     = calc_roi(results)
    net     = roi["net_units"]
    sign    = "+" if net >= 0 else ""
    arrow   = "📈" if net >= 0 else "📉"
    caveat  = f"  ({roi['bets_no_odds']} picks used -110 default)" if roi["bets_no_odds"] else ""

    lines = [
        f"  {arrow} ROI:       {sign}{roi['roi_pct']:.1f}%  ({sign}{net:.2f} units on {roi['total']} bets)",
    ]
    if caveat:
        lines.append(f"  ℹ️  {caveat.strip()}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────

def print_report(results: list):
    if not results:
        print("\n  No results logged yet. Run: python results_tracker.py")
        return

    # Backfill version on any result that's missing it
    for r in results:
        if not r.get("model_version"):
            r["model_version"] = infer_version_from_date(r.get("date", ""))

    print(f"\n{'═'*60}")
    print(f"  📊 RESULTS REPORT  |  Culture & Pulse Analytics")
    print(f"  Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    print(f"{'═'*60}")

    total   = len(results)
    wins    = sum(1 for r in results if r["won"])
    losses  = total - wins
    win_pct = (wins / total * 100) if total > 0 else 0

    print(f"\n  OVERALL (all versions)")
    print(f"  {'─'*40}")
    print(f"  Record:    {wins}W - {losses}L  ({win_pct:.1f}%)")
    print(f"  Total:     {total} bets logged")
    print(format_roi_block(results))

    # By model version
    print(f"\n  BY MODEL VERSION")
    print(f"  {'─'*40}")
    for version in ["v1", "v2", "v3"]:
        vr = [r for r in results if r.get("model_version") == version]
        if not vr:
            continue
        vw  = sum(1 for r in vr if r["won"])
        vp  = (vw / len(vr) * 100)
        tag = VERSION_LABELS.get(version, version)
        roi = calc_roi(vr)
        sign = "+" if roi["net_units"] >= 0 else ""
        print(f"  {tag}")
        print(f"  {'':4}{vw}W-{len(vr)-vw}L  ({vp:.0f}%)  |  {sign}{roi['net_units']:.2f}u  {sign}{roi['roi_pct']:.1f}% ROI  —  {len(vr)} games")

    # Current version only summary
    v3 = [r for r in results if r.get("model_version") == "v3"]
    if v3:
        v3w = sum(1 for r in v3 if r["won"])
        v3p = (v3w / len(v3) * 100) if v3 else 0
        print(f"\n  ★ CURRENT MODEL (v3) RECORD")
        print(f"  {'─'*40}")
        print(f"  Record:    {v3w}W - {len(v3)-v3w}L  ({v3p:.1f}%)")
        print(f"  Total:     {len(v3)} games tracked")
        print(format_roi_block(v3))

        # By sport — v3 only
        sports = sorted(set(r["sport"] for r in v3))
        if len(sports) > 1:
            print(f"\n  BY SPORT (v3 only)")
            print(f"  {'─'*40}")
            for sport in sports:
                sr   = [r for r in v3 if r["sport"] == sport]
                sw   = sum(1 for r in sr if r["won"])
                sp   = (sw / len(sr) * 100)
                roi  = calc_roi(sr)
                sign = "+" if roi["net_units"] >= 0 else ""
                print(f"  {sport:<6}  {sw}W-{len(sr)-sw}L  ({sp:.0f}%)  |  {sign}{roi['net_units']:.2f}u")

        # By edge tier — v3 only
        print(f"\n  BY EDGE TIER (v3 only)")
        print(f"  {'─'*40}")
        tiers = [
            ("★★★ STRONG  (8%+)",  lambda r: r.get("edge", 0) >= 8),
            ("★★ MODERATE (5-8%)", lambda r: 5 <= r.get("edge", 0) < 8),
            ("★ SLIGHT    (<5%)",  lambda r: r.get("edge", 0) < 5),
        ]
        for label, fn in tiers:
            tr = [r for r in v3 if fn(r)]
            if not tr:
                continue
            tw   = sum(1 for r in tr if r["won"])
            tp   = (tw / len(tr) * 100)
            roi  = calc_roi(tr)
            sign = "+" if roi["net_units"] >= 0 else ""
            print(f"  {label}  {tw}W-{len(tr)-tw}L  ({tp:.0f}%)  |  {sign}{roi['net_units']:.2f}u")
    else:
        # Fall back to full history if v3 has no results yet
        sports = sorted(set(r["sport"] for r in results))
        if len(sports) > 1:
            print(f"\n  BY SPORT")
            print(f"  {'─'*40}")
            for sport in sports:
                sr   = [r for r in results if r["sport"] == sport]
                sw   = sum(1 for r in sr if r["won"])
                sp   = (sw / len(sr) * 100)
                roi  = calc_roi(sr)
                sign = "+" if roi["net_units"] >= 0 else ""
                print(f"  {sport:<6}  {sw}W-{len(sr)-sw}L  ({sp:.0f}%)  |  {sign}{roi['net_units']:.2f}u")

        print(f"\n  BY EDGE TIER")
        print(f"  {'─'*40}")
        tiers = [
            ("★★★ STRONG  (8%+)",  lambda r: r.get("edge", 0) >= 8),
            ("★★ MODERATE (5-8%)", lambda r: 5 <= r.get("edge", 0) < 8),
            ("★ SLIGHT    (<5%)",  lambda r: r.get("edge", 0) < 5),
        ]
        for label, fn in tiers:
            tr = [r for r in results if fn(r)]
            if not tr:
                continue
            tw   = sum(1 for r in tr if r["won"])
            tp   = (tw / len(tr) * 100)
            roi  = calc_roi(tr)
            sign = "+" if roi["net_units"] >= 0 else ""
            print(f"  {label}  {tw}W-{len(tr)-tw}L  ({tp:.0f}%)  |  {sign}{roi['net_units']:.2f}u")

    # Last 5 — always from full history
    print(f"\n  LAST 5 BETS")
    print(f"  {'─'*40}")
    for r in results[-5:][::-1]:
        icon = "✅" if r["won"] else "❌"
        ver  = r.get("model_version", "??")
        print(f"  {icon} {r['date']}  [{ver}]  {r['game'][:32]:<32}  {r['bet']}")

    print(f"\n{'═'*60}\n")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = load_results()
    cmd     = sys.argv[1].lower() if len(sys.argv) > 1 else "auto"

    if cmd == "report":
        print_report(results)

    elif cmd == "reset":
        confirm = input("  ⚠  This will clear ALL logged results. Type YES to confirm: ").strip()
        if confirm == "YES":
            save_results([])
            print("  Results log cleared.")
        else:
            print("  Cancelled.")

    else:
        results = auto_pull_results(results)
        save_results(results)
        print_report(results)
