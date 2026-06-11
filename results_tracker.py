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

# Cache ESPN results per sport per date to avoid repeat calls
_espn_cache: dict = {}


# ─────────────────────────────────────────────────────────────
# ESPN RESULT FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_espn_results(sport: str, date_str: str) -> list:
    """
    Fetch completed game results from ESPN for a given sport and date.
    date_str format: YYYY-MM-DD
    Returns list of { event_id, home_team, away_team, home_score, away_score, winner }
    """
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
    """Fuzzy match a team name against ESPN results."""
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
    """
    Look up the actual winner for a game from ESPN.
    Uses event_id for exact match when available, falls back to fuzzy team name match.
    Returns team name string or empty string if not found/not completed.
    """
    games = fetch_espn_results(sport, date_str)
    if not games:
        return ""

    # ── Exact match by event_id (preferred) ──
    if event_id:
        for g in games:
            if g.get("event_id") == event_id:
                return g["winner"]

    # ── Fallback: fuzzy team name match ──
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
    """
    Scans all prediction JSONs in data/predictions/.
    For each game missing actual_winner, fetches result from ESPN.
    Updates the prediction JSON and appends to results_log.
    """
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

        game       = pred.get("game", "")
        sport      = pred.get("sport", "").lower()
        date_str   = pred.get("date", "")
        bet_label  = pred.get("bet", "")
        model_prob = pred.get("model_prob", 50)
        edge       = pred.get("edge", 0)
        odds       = pred.get("odds", "N/A")
        event_id   = pred.get("event_id", "")

        # Skip if actual result already filled in
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
                               odds, model_prob, edge, actual_winner, won)
                new_count += 1
            continue

        # Skip future games
        try:
            game_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if game_date >= today:
                pending += 1
                continue
        except Exception:
            pass

        # Parse teams
        parts     = game.split(" @ ")
        away_team = parts[0] if len(parts) == 2 else ""
        home_team = parts[1] if len(parts) == 2 else ""

        if not sport or not date_str or not home_team:
            not_found += 1
            continue

        # Fetch from ESPN (event_id used for exact match when available)
        winner = find_actual_winner(sport, date_str, home_team, away_team, event_id)

        if not winner:
            print(f"  ⚠  No ESPN result: {game} ({date_str})")
            not_found += 1
            continue

        # Update prediction JSON with actual result
        pred["actual_result"]["actual_winner"] = winner
        with open(filepath, "w") as f:
            json.dump(pred, f, indent=2)

        # Determine W/L
        bet_on_home      = home_team in bet_label
        predicted_winner = home_team if bet_on_home else away_team
        won = (predicted_winner.lower() in winner.lower() or
               winner.lower() in predicted_winner.lower())
        result_str = "✅ WIN" if won else "❌ LOSS"

        print(f"  {result_str}  {game}  |  Bet: {bet_label}  |  Winner: {winner}")

        if not result_exists(game, date_str, results):
            _append_result(results, pred, game, sport, date_str, bet_label,
                           odds, model_prob, edge, winner, won)
            new_count += 1

    print(f"\n  {new_count} new result(s) logged.")
    if pending:
        print(f"  {pending} game(s) pending (future dates).")
    if not_found:
        print(f"  {not_found} game(s) not found on ESPN yet.")

    return results


def _append_result(results, pred, game, sport, date_str, bet_label,
                   odds, model_prob, edge, actual_winner, won):
    """Build and append a result entry to results list."""
    results.append({
        "game":          game,
        "sport":         sport.upper(),
        "date":          date_str,
        "event_id":      pred.get("event_id", ""),
        "bet":           bet_label,
        "odds":          odds,
        "model_prob":    model_prob,
        "edge":          edge,
        "actual_winner": actual_winner,
        "won":           won,
        "logged_at":     datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


# ─────────────────────────────────────────────────────────────
# REPORT
# ─────────────────────────────────────────────────────────────

def print_report(results: list):
    if not results:
        print("\n  No results logged yet. Run: python results_tracker.py")
        return

    print(f"\n{'═'*60}")
    print(f"  📊 RESULTS REPORT  |  Culture & Pulse Analytics")
    print(f"  Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    print(f"{'═'*60}")

    total   = len(results)
    wins    = sum(1 for r in results if r["won"])
    losses  = total - wins
    win_pct = (wins / total * 100) if total > 0 else 0

    print(f"\n  OVERALL")
    print(f"  {'─'*40}")
    print(f"  Record:    {wins}W - {losses}L  ({win_pct:.1f}%)")
    print(f"  Total:     {total} bets logged")

    # By sport
    sports = sorted(set(r["sport"] for r in results))
    if len(sports) > 1:
        print(f"\n  BY SPORT")
        print(f"  {'─'*40}")
        for sport in sports:
            sr = [r for r in results if r["sport"] == sport]
            sw = sum(1 for r in sr if r["won"])
            sp = (sw / len(sr) * 100)
            print(f"  {sport:<6}  {sw}W-{len(sr)-sw}L  ({sp:.0f}%)")

    # By edge tier
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
        tw = sum(1 for r in tr if r["won"])
        tp = (tw / len(tr) * 100)
        print(f"  {label}  {tw}W-{len(tr)-tw}L  ({tp:.0f}%)")

    # Recent results
    print(f"\n  LAST 5 BETS")
    print(f"  {'─'*40}")
    for r in results[-5:][::-1]:
        icon = "✅" if r["won"] else "❌"
        print(f"  {icon} {r['date']}  {r['game'][:35]:<35}  {r['bet']}")

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
