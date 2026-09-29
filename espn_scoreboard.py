"""
espn_scoreboard.py — Culture & Pulse Analytics
=======================================================
Single shared get_espn_game_ids() for every sport's player-game-log
updater. Consolidated 2026-09-10 — wnba_player_stats.py,
mlb_player_stats.py, cfb_player_game_logs.py,
backfill/nfl/nfl_player_game_logs.py, and backfill/nba/nba_player_stats.py
each carried a byte-near-identical copy of this function, all with the
same bug: a JSON parse failure (`Expecting value: line 1 column 1
(char 0)`, seen across WNBA/NFL/CFB all week) was caught and printed
with no status code or raw response body — the actual cause (empty
body? HTML error page? 429? 403?) was never visible, only the
downstream symptom of trying to parse whatever came back. Same
duplication risk already found and fixed once for services/odds_parser.py
— one copy getting a fix while the other 4 don't.

Usage:
    from espn_scoreboard import get_espn_game_ids
    game_ids = get_espn_game_ids("wnba", "20260910")
"""

import os
import requests
from urllib.parse import urlencode

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

ESPN_SCOREBOARD_BASE = "https://site.api.espn.com/apis/site/v2/sports"

# ScraperAPI proxy — GitHub Actions' runner IP range has been hard-403'd
# by ESPN's WAF since 2026-09-12 (confirmed via 17 straight days of NFL
# Stats Backfill failures); Render and local runs are NOT blocked
# (confirmed 2026-09-11 via live Render log pull), so only route through
# ScraperAPI when actually running on a GitHub Actions runner — no point
# spending ScraperAPI credits on traffic that already gets through direct.
# Same `http://api.scraperapi.com?api_key=...&url=...` shape as the
# pattern auto_results.py/prop_tracker.py used before it was stripped out
# 2026-08-21 ("call ESPN directly") — that removal predates this block
# and was fine at the time; reintroducing it here, scoped to GitHub
# Actions only, not restoring it unconditionally everywhere.
SCRAPERAPI_URL = "http://api.scraperapi.com"

_scraperapi_calls = 0


def get_scraperapi_call_count() -> int:
    return _scraperapi_calls


def reset_scraperapi_call_count():
    global _scraperapi_calls
    _scraperapi_calls = 0


def _scraperapi_key() -> str:
    """Returns the ScraperAPI key to use for this call, or '' to go direct.
    Gated on GITHUB_ACTIONS (set to "true" automatically by every GitHub
    Actions runner, no workflow config needed) so Render/local traffic
    never gets routed through the proxy."""
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() != "true":
        return ""
    return os.environ.get("SCRAPERAPI_KEY", "").strip()


def espn_get(url: str, params: dict = None, headers: dict = None, timeout: int = 10):
    """Shared GET for any site.api.espn.com call (scoreboard or box
    score/summary). Routes through ScraperAPI when running in GitHub
    Actions and SCRAPERAPI_KEY is set — see module docstring. Builds the
    real ESPN URL (with query params) first and hands the WHOLE thing to
    ScraperAPI as its own `url` param, since ScraperAPI proxies arbitrary
    URLs rather than being an ESPN-specific client."""
    global _scraperapi_calls
    headers = headers or HEADERS
    key = _scraperapi_key()
    if not key:
        return requests.get(url, headers=headers, params=params, timeout=timeout)

    real_url = f"{url}?{urlencode(params)}" if params else url
    _scraperapi_calls += 1
    return requests.get(
        SCRAPERAPI_URL,
        params={"api_key": key, "url": real_url},
        headers=headers,
        timeout=timeout,
    )


# Tracks scoreboard fetch failures (non-200, exception, JSON parse failure)
# since process start or the last reset — lets callers tell "ESPN said zero
# games" apart from "ESPN wouldn't answer" (blocked/erroring), e.g. NFL's
# zero-games guard in backfill/nfl/nfl_player_game_logs.py.
_scoreboard_errors = 0


def get_scoreboard_error_count() -> int:
    return _scoreboard_errors


def reset_scoreboard_error_count():
    global _scoreboard_errors
    _scoreboard_errors = 0

# Per-sport ESPN path + any extra query params, matching each original
# file's own call exactly (only CFB carried &limit=200 — its heavier
# 130+-team slate needs it to avoid ESPN's endpoint truncating results;
# not touching that here, that's a separate, already-known concern).
SPORT_PATHS = {
    "nfl":  "football/nfl",
    "cfb":  "football/college-football",
    "nba":  "basketball/nba",
    "wnba": "basketball/wnba",
    "mlb":  "baseball/mlb",
}
SPORT_EXTRA_PARAMS = {
    "cfb": {"limit": 200},
}


def get_espn_game_ids(sport: str, date_str: str, timeout: int = 10) -> list:
    """Get all completed game IDs for a given sport and date (YYYYMMDD).

    On any failure — request exception, non-200 status, or a JSON
    decode failure — logs status code, content-type, and the first 300
    chars of the raw response body BEFORE giving up, instead of only
    the downstream JSON-decode error. Added 2026-09-10 after a week of
    silent "Scoreboard error: Expecting value..." failures across
    WNBA/NFL/CFB gave no clue what ESPN was actually returning; this
    instruments the next real occurrence instead of guessing at it."""
    sport_path = SPORT_PATHS.get(sport)
    if not sport_path:
        print(f"  Scoreboard error {date_str}: no ESPN path configured for sport '{sport}'")
        return []

    url = f"{ESPN_SCOREBOARD_BASE}/{sport_path}/scoreboard"
    params = dict(SPORT_EXTRA_PARAMS.get(sport, {}))
    params["dates"] = date_str

    global _scoreboard_errors

    try:
        r = espn_get(url, params=params, headers=HEADERS, timeout=timeout)
    except Exception as e:
        print(f"  Scoreboard error {date_str} ({sport}): request failed — {type(e).__name__}: {e}")
        _scoreboard_errors += 1
        return []

    if r.status_code != 200:
        print(f"  Scoreboard error {date_str} ({sport}): status={r.status_code} "
              f"content-type={r.headers.get('content-type')!r} body={r.text[:300]!r}")
        _scoreboard_errors += 1
        return []

    try:
        data = r.json()
    except Exception as e:
        print(f"  Scoreboard error {date_str} ({sport}): JSON parse failed ({e}) — "
              f"status={r.status_code} content-type={r.headers.get('content-type')!r} "
              f"body={r.text[:300]!r}")
        _scoreboard_errors += 1
        return []

    ids = []
    for event in data.get("events", []):
        completed = event.get("status", {}).get("type", {}).get("completed", False)
        if completed:
            ids.append(event.get("id"))
    return ids
