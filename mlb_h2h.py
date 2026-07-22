"""
mlb_h2h.py - Culture & Pulse Analytics
Head-to-head matchup history between two MLB teams this season.

v3 (2026-07-22): added lru_cache — this was the real gap in the
two-pass matchup fix. get_h2h_record() was running UNCONDITIONALLY
for every game in both passes (unlike matchup, which was correctly
gated behind candidate filtering), hitting ESPN's team-schedule
endpoint — a genuinely large payload (full team objects with 8+ logo
URLs each, plus the team's full season schedule) — once per game,
with up to 6 of these firing concurrently via the thread pool. This
is the most likely cause of the process crashing (not just timing
out) shortly after starting a full slate.

Cached per team_id for the life of the process — the same team's
schedule doesn't change mid-run, and a team appearing in multiple
games (doubleheaders) previously meant fetching this same large
payload twice.

v2: uses the real "winner": true/false flag ESPN returns — no
guessing at score field shapes.

v1: computed LIVE from ESPN schedule data each call, no new DB table
required.

Sample size caveat: two teams may only play each other 3-19 times a
season (fewer if interleague). Real signal, small sample — the
adjustment is deliberately damped.
"""

import requests
from functools import lru_cache

ESPN_TEAM_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{team_id}/schedule"


@lru_cache(maxsize=32)
def _fetch_team_schedule(team_id: str) -> tuple:
    """
    Raw ESPN schedule fetch for one team, cached per team_id for the
    life of the process. Returns a tuple (not a list/dict) so it's
    hashable-safe for lru_cache's own internal bookkeeping — the
    caller reconstructs what it needs from this.

    This is the actual fix: previously every call to get_h2h_record()
    re-fetched this same large payload from scratch, even for the
    same team across multiple calls in one run (doubleheaders, or
    simply being on both a home and away slate elsewhere that day).
    """
    url = ESPN_TEAM_SCHEDULE_URL.format(team_id=team_id)
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        return tuple(data.get("events", []))
    except Exception as e:
        print(f"  H2H schedule fetch error (team_id={team_id}): {e}")
        return ()


def get_h2h_record(team_id: str, team_name: str, opponent_name: str) -> dict:
    """
    Pulls team_id's completed games this season against opponent_name.
    Returns {"games": int, "wins": int, "losses": int} or all-zero
    dict if the API call fails or no matchups found yet.
    """
    empty = {"games": 0, "wins": 0, "losses": 0}

    events = _fetch_team_schedule(team_id)
    if not events:
        return empty

    record = dict(empty)
    for event in events:
        comp = event.get("competitions", [{}])[0]
        status = comp.get("status", {}).get("type", {})
        if not status.get("completed", False):
            continue

        competitors = comp.get("competitors", [])
        opponent_present = any(
            c.get("team", {}).get("displayName", "") == opponent_name
            for c in competitors
        )
        if not opponent_present:
            continue  # this game wasn't against the opponent we're checking

        team_comp = next(
            (c for c in competitors if c.get("team", {}).get("displayName", "") == team_name),
            None,
        )
        if team_comp is None:
            continue

        record["games"] += 1
        if team_comp.get("winner") is True:
            record["wins"] += 1
        else:
            record["losses"] += 1

    return record


def get_h2h_adj(record: dict) -> float:
    """
    Converts a H2H win/loss record into a small run adjustment.
    Damped hard on purpose — small sample size (season series is
    usually well under 20 games), so this should nudge, not drive,
    the projection. Returns 0.0 if fewer than 3 games played (not
    enough signal to trust at all).
    """
    if record["games"] < 3:
        return 0.0

    win_pct = record["wins"] / record["games"]
    diff = win_pct - 0.5  # positive = team has historically beaten this opponent more than 50/50

    # Damped to half the raw win-pct differential, expressed as runs —
    # e.g. a lopsided .800 series (diff=0.3) nudges +0.15 runs, not a
    # season-swinging adjustment.
    return round(diff * 0.5, 3)
