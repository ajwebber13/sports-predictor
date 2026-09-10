"""
services/odds_parser.py
Primary: ESPN free API (no key needed, no credit cost)
Fallback: The Odds API (real DraftKings/FanDuel lines) — demoted
2026-09-08, kept working rather than removed in case ESPN's
undocumented endpoint ever breaks or gets rate-limited unexpectedly.
Same output format for all downstream code.
"""
import requests
import os
import time
import json
from datetime import datetime, timezone, timedelta

CENTRAL_OFFSET = -5  # CDT
API_KEY        = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE  = "https://api.the-odds-api.com/v4"

# In-process cache for get_live_odds() — added 2026-09-08 after the
# Odds API's 500-credit/month cap got burned through in days. Traced
# the actual redundancy: a single render_job.py run for one sport calls
# get_live_odds() directly (once in run_alerts() for log_odds(), again
# for line-movement tracking on a --retry run) AND the /edges route
# calls it again internally when render_job.py hits that endpoint over
# HTTP — and if fetch_edges_with_retry() has to retry a failed attempt,
# the route's internal odds call fires again too, even when the odds
# data itself didn't need refetching.
#
# TTL, not a run-scoped flag: this module can't know when one
# render_job.py "run" starts or ends — it's a stateless function, and
# the /edges route runs in a completely separate deployed process from
# render_job.py (reached over HTTP, no shared memory), so there's no
# single process boundary to hang a "this run" cache on either. 600s
# (10 min) comfortably spans one run's full length, including
# worst-case 3x-retry backoffs, while staying far short of the
# multi-hour gap between scheduled runs (morning vs noon vs 3pm retry)
# — so the cross-run staleness line-movement tracking specifically
# depends on not having can't happen; each new scheduled run is hours
# past any previous cache entry's TTL and always misses.
_odds_cache: dict = {}
_ODDS_CACHE_TTL_SECONDS = 600

# Persistent cache for the ODDS API FALLBACK specifically (2026-09-09)
# — separate from _odds_cache above, which stays in-memory and
# unchanged for the ESPN-primary path. ESPN is free (no credit cost),
# so an in-memory, per-process cache was never the actual problem
# there; the real cost sits on the Odds API branch, which only fires
# when ESPN comes back empty. render_job.py runs as a fresh,
# ephemeral process on every scheduled run, retry, and manual
# trigger — Render's cron jobs don't share a filesystem or memory
# between runs — so _odds_cache resetting every time meant every one
# of those re-hit the Odds API from scratch even for the same
# sport+date, which is exactly what burned the account's monthly
# credits down in days (see the 2026-09-08 cache comment above, and
# the 2026-09-09 OUT_OF_USAGE_CREDITS incident this table fixes).
# Stored in the shared DB via database.get_conn() — the one thing
# that actually persists across those ephemeral runs — keyed by
# (sport, cache_date) so a cross-midnight run can't reuse yesterday's
# odds, with a 2-hour TTL (odds don't need refreshing more often than
# that, and it's short enough that a real line move on a longer-
# running day still gets picked up well before game time).
ODDS_API_CACHE_TTL_SECONDS = 7200


def _get_today_ct_str() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).strftime("%Y-%m-%d")


def _read_odds_api_cache(sport: str, cache_date: str):
    """Returns cached Odds API games for (sport, cache_date) if a row
    exists and is within ODDS_API_CACHE_TTL_SECONDS, else None (miss,
    expired, or any read error — a cache problem degrades to a real
    API call rather than breaking the run)."""
    try:
        from database import get_conn
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT games_json, cached_at FROM odds_api_cache WHERE sport = ? AND cache_date = ?",
            (sport, cache_date),
        )
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        if time.time() - row["cached_at"] >= ODDS_API_CACHE_TTL_SECONDS:
            return None
        return json.loads(row["games_json"])
    except Exception as e:
        print(f"  Odds API cache read error ({sport}): {e}")
        return None


def _write_odds_api_cache(sport: str, cache_date: str, games: list):
    """Best-effort — a failed cache write must never block returning
    real data to the caller, so this only ever prints on error."""
    try:
        from database import get_conn
        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO odds_api_cache (sport, cache_date, cached_at, games_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (sport, cache_date) DO UPDATE SET
                cached_at  = EXCLUDED.cached_at,
                games_json = EXCLUDED.games_json
        """, (sport, cache_date, int(time.time()), json.dumps(games)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  Odds API cache write error ({sport}): {e}")


ODDS_API_SPORT_KEYS = {
    "nfl":   "americanfootball_nfl",
    "ncaaf": "americanfootball_ncaaf",
    "cfb":   "americanfootball_ncaaf",
    "nba":   "basketball_nba",
    "ncaab": "basketball_ncaab",
    "ncaaw": "basketball_wncaab",
    "wnba":  "basketball_wnba",
}

ESPN_ENDPOINTS = {
    "nfl":   "football/nfl",
    "ncaaf": "football/college-football",
    "cfb":   "football/college-football",
    "nba":   "basketball/nba",
    "ncaab": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
    "wnba":  "basketball/wnba",
}

ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept":     "application/json",
    "Referer":    "https://www.espn.com/",
}


def _get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


# ── THE ODDS API (fallback — demoted 2026-09-08) ────────────────────────

def get_odds_api(sport: str):
    """Pull live moneyline odds from The Odds API — DraftKings/FanDuel lines.

    Returns a list on success (empty list is a genuine "no games right
    now" response) or None on a real request failure — 2026-09-09,
    changed from always-returns-a-list so get_live_odds() can tell
    "the API said zero games" apart from "the call itself failed" and
    only persistently cache the former. Caching a failure as if it were
    a real empty result would otherwise block the noon/3pm retry from
    ever trying again for up to ODDS_API_CACHE_TTL_SECONDS, defeating
    the entire point of having a retry. The only caller is
    get_live_odds() in this same module, so this contract change is
    self-contained."""
    if not API_KEY:
        return []

    sport_key = ODDS_API_SPORT_KEYS.get(sport)
    if not sport_key:
        return []

    try:
        r = requests.get(
            f"{ODDS_API_BASE}/sports/{sport_key}/odds",
            params={
                "apiKey":     API_KEY,
                "regions":    "us",
                "markets":    "h2h,spreads,totals",
                "bookmakers": "draftkings,fanduel",
                "oddsFormat": "american",
            },
            timeout=10
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"Odds API error ({sport}): {e}")
        return None

    games = []
    for game in data:
        games.append({
            "home_team":     game.get("home_team", ""),
            "away_team":     game.get("away_team", ""),
            "commence_time": game.get("commence_time", ""),
            "event_id":      game.get("id", ""),
            "bookmakers":    game.get("bookmakers", []),
        })

    print(f"Odds API returned {len(games)} game(s) for {sport}")
    return games


# ── ESPN (primary — promoted 2026-09-08) ────────────────────────────────

def get_espn_odds(sport: str) -> list:
    """Pull today's games from ESPN free API.

    PROMOTED TO PRIMARY 2026-09-08 — see get_live_odds() below.

    FIXED same day: ESPN's scoreboard endpoint silently defaults to an
    arbitrary ~25-event subset when called with no params — the exact
    issue already found and fixed for cfb_data.get_cfb_events()/
    telegram_alerts.get_game_times() weeks ago, but this function never
    got that same fix, since until today it was only ever a rarely-hit
    fallback. Confirmed live: CFB without groups=80&limit=200 returned
    24 of 86 real games for this week, missing nearly all of Saturday's
    slate — a silent, serious coverage gap now that this path is
    primary. NFL doesn't need this (32 teams, one coherent weekly
    slate — same reasoning as the earlier fix)."""
    endpoint = ESPN_ENDPOINTS.get(sport)
    if not endpoint:
        return []

    url    = f"{ESPN_BASE}/{endpoint}/scoreboard"
    params = {}
    if sport == "cfb":
        params = {"groups": "80", "limit": 200}
    today_ct = _get_today_ct()

    try:
        r    = requests.get(url, headers=HEADERS, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ESPN error ({sport}): {e}")
        return []

    games = []
    for event in data.get("events", []):
        try:
            game_date = event.get("date", "")
            # Same-day filter — correct for WNBA/MLB/CFB, whose real
            # slate for a given calendar day IS that day's games.
            # DELIBERATE EXCEPTION for NFL (2026-09-10): its real slate
            # spans Thu-Mon, not one calendar day — this filter was
            # throwing out the rest of the week every day but game day.
            # Confirmed live: ESPN returned 16 real NFL games across 4
            # distinct dates for the week, and this filter kept exactly
            # 1. Also defeats odds_history's actual purpose for NFL
            # specifically — logging today's price on a game that
            # plays out LATER in the week is exactly how line-movement
            # tracking is supposed to work; skipping non-today games
            # means NFL can never have a real opening line captured
            # days ahead of kickoff. Do NOT add this filter back for
            # NFL — completed games are still excluded below via the
            # status check, regardless of sport.
            if game_date and sport != "nfl":
                utc_dt     = datetime.fromisoformat(game_date.replace("Z", "+00:00"))
                central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
                if central_dt.date() != today_ct:
                    continue

            status = event.get("status", {}).get("type", {}).get("name", "")
            if any(x in status for x in ["Final", "STATUS_FINAL"]):
                continue

            comp        = event.get("competitions", [{}])[0]
            competitors = comp.get("competitors", [])
            home = next((t for t in competitors if t["homeAway"] == "home"), None)
            away = next((t for t in competitors if t["homeAway"] == "away"), None)
            if not home or not away:
                continue

            home_name = home["team"]["displayName"]
            away_name = away["team"]["displayName"]

            odds_data  = comp.get("odds", [{}])
            odds_obj   = odds_data[0] if odds_data else {}

            # No silent fallback here — a missing real moneyline is
            # "we don't have this game's real price," not "-110 both
            # sides." That defaulting is exactly the fabricated-odds
            # pattern this project already found and fixed once
            # (the July 9 incident, a different code path). If ESPN
            # doesn't have a real number, this game gets NO h2h market
            # at all — downstream code (log_odds, log_prediction,
            # calculate_roi/calculate_clv) already handles a missing/
            # None odds value correctly by excluding it, rather than
            # silently trusting a fake symmetric line.
            #
            # FIXED 2026-09-08: was odds_obj.get("homeTeamOdds", {}).
            # get("moneyLine") / awayTeamOdds — that path doesn't exist
            # in ESPN's actual schema (homeTeamOdds/awayTeamOdds only
            # carry favorite/underdog flags), so has_real_ml was False
            # for every game, always, and this "no fallback" comment's
            # intent was silently defeated the whole time — h2h simply
            # never populated regardless of whether ESPN had a real
            # price. Confirmed live: the real moneyline lives at
            # odds_obj["moneyline"]["home"/"away"]["close"]["odds"]
            # (a string like "-170"), a completely different structure.
            moneyline_obj = odds_obj.get("moneyline", {})
            raw_home_ml = moneyline_obj.get("home", {}).get("close", {}).get("odds")
            raw_away_ml = moneyline_obj.get("away", {}).get("close", {}).get("odds")
            has_real_ml = raw_home_ml is not None and raw_away_ml is not None

            # FIXED 2026-09-08: was odds_obj.get("spread", 0) / .get(
            # "overUnder", 0) — defaulting to 0 whenever a game had no
            # real odds object at all (comp.get("odds") is None; confirmed
            # live for ~1/3 of CFB games — DraftKings, ESPN's only
            # provider, doesn't price every buy game). 0 is a real,
            # meaningful spread/total value (a true pick'em / even
            # total), indistinguishable from "no data" once defaulted —
            # exactly the fabricated-line problem the comment above
            # already describes fixing for moneyline, just still present
            # here. No default now: a missing key correctly comes back
            # None, and the guards below skip adding that market entirely
            # rather than inventing a line, matching how The Odds API
            # path already behaves for a game it has no coverage for
            # (that game simply doesn't appear in events_odds at all).
            spread     = odds_obj.get("spread")
            over_under = odds_obj.get("overUnder")

            markets = []
            if has_real_ml:
                markets.append({
                    "key": "h2h",
                    "outcomes": [
                        {"name": home_name, "price": int(raw_home_ml)},
                        {"name": away_name, "price": int(raw_away_ml)},
                    ]
                })
            else:
                print(f"  [ESPN] no real moneyline for {away_name} @ {home_name} — "
                      f"skipping h2h market rather than defaulting to -110/-110")

            # Prices legitimately default to -110 — that's the real,
            # standard vig price books use for point spreads and totals.
            # The LINE itself (spread/over_under) never defaults, per the
            # fix above — only added when ESPN actually has one.
            if spread is not None:
                markets.append({
                    "key": "spreads",
                    "outcomes": [
                        {"name": home_name, "point": spread, "price": -110},
                        {"name": away_name, "point": -spread if spread else 0, "price": -110},
                    ]
                })
            if over_under is not None:
                markets.append({
                    "key": "totals",
                    "outcomes": [
                        {"name": "Over",  "point": over_under, "price": -110},
                        {"name": "Under", "point": over_under, "price": -110},
                    ]
                })

            games.append({
                "home_team":     home_name,
                "away_team":     away_name,
                "commence_time": game_date,
                "event_id":      event.get("id", ""),
                "bookmakers": [{
                    "key":     "espn",
                    "title":   "ESPN",
                    "markets": markets,
                }]
            })
        except Exception:
            continue

    print(f"ESPN returned {len(games)} game(s) for {sport}")
    return games


# ── MAIN FUNCTION ────────────────────────────────────────────────────────

def get_live_odds(sport: str = "nba") -> list:
    """
    Primary: ESPN free API — no key, no credit cost. Real DraftKings
    lines (confirmed live: 100% DraftKings-provided, 0.0 spread
    difference against The Odds API's own DraftKings line across every
    matched NFL game checked) at effectively zero ongoing cost.
    Fallback: The Odds API — demoted 2026-09-08, not removed, so a
    working key is still there if ESPN's undocumented endpoint ever
    breaks or gets rate-limited unexpectedly.

    CACHED — see _ODDS_CACHE_TTL_SECONDS above. Every call for this
    sport within the TTL window reuses the same result, whether it
    comes from render_job.py's own direct calls or the /edges route's
    internal call (including across fetch_edges_with_retry()'s retry
    attempts) — same data, no reason to hit the network twice. An
    empty result is cached too, deliberately: if ESPN has nothing right
    now, retrying it seconds later within the same run won't get a
    different answer, so there's nothing to gain from hitting it again
    before the TTL expires. This in-memory cache is ESPN-only and
    unchanged from 2026-09-08 — ESPN is free, so a per-process cache
    resetting on every run was never the actual cost problem.

    ODDS API FALLBACK — separately, persistently cached (2026-09-09,
    see ODDS_API_CACHE_TTL_SECONDS above) via the shared DB, since this
    branch is the one that actually burns real, limited monthly
    credits and render_job.py runs as a fresh process every time. Only
    reached when ESPN comes back empty — the ESPN-primary path above
    is untouched by this.
    """
    now = time.time()
    cached = _odds_cache.get(sport)
    if cached is not None and (now - cached[0]) < _ODDS_CACHE_TTL_SECONDS:
        return cached[1]

    # Try ESPN first
    games = get_espn_odds(sport)
    if games:
        _odds_cache[sport] = (now, games)
        return games
    print(f"  ESPN empty for {sport} — falling back to Odds API")

    # Fall back to the Odds API (demoted, not removed) — persistent
    # cache checked first so a same-day retry/manual-trigger reuses a
    # recent fetch instead of spending another credit.
    cache_date = _get_today_ct_str()
    cached_games = _read_odds_api_cache(sport, cache_date)
    if cached_games is not None:
        print(f"  Odds API cache hit for {sport} ({cache_date}) — {len(cached_games)} game(s), no credit spent")
        _odds_cache[sport] = (now, cached_games)
        return cached_games

    if API_KEY:
        games = get_odds_api(sport)
        if games is None:
            # Real request failure, not a genuine "0 games" response —
            # do NOT persist this as a cache hit, or a transient error
            # would block every retry for the next 2 hours instead of
            # letting the noon/3pm retry actually try again.
            games = []
        else:
            _write_odds_api_cache(sport, cache_date, games)
        _odds_cache[sport] = (now, games)
        return games

    _odds_cache[sport] = (now, [])
    return []


# ── HELPERS ──────────────────────────────────────────────────────────────

def parse_moneyline(game: dict) -> dict:
    home_team  = game.get("home_team", "")
    away_team  = game.get("away_team", "")
    home_probs = []
    away_probs = []

    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "h2h":
                for outcome in market.get("outcomes", []):
                    implied = american_to_implied(outcome["price"])
                    if outcome["name"] == home_team:
                        home_probs.append(implied)
                    elif outcome["name"] == away_team:
                        away_probs.append(implied)

    if not home_probs or not away_probs:
        return None

    raw_home = sum(home_probs) / len(home_probs)
    raw_away = sum(away_probs) / len(away_probs)
    total    = raw_home + raw_away

    return {
        home_team: round((raw_home / total) * 100, 1),
        away_team: round((raw_away / total) * 100, 1),
    }


def parse_spread(game: dict):
    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "spreads":
                return market["outcomes"]
    return None


def parse_totals(game: dict):
    for bookmaker in game.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market["key"] == "totals":
                return market["outcomes"]
    return None


def american_to_implied(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)