"""
mlb_h2h.py - Culture & Pulse Analytics
Head-to-head matchup history between two MLB teams this season.

v2 (2026-07-22): rebuilt after live debug confirmed each ESPN
competitor object carries a direct "winner": true/false flag — no
need to parse/guess at score field shapes. Simpler and more reliable
than the original run-differential approach. Win/loss record only,
no run differential.

v1: computed LIVE from ESPN schedule data each call, no new DB table
required. Reuses the same ESPN schedule endpoint get_team_rest_days()
in mlb_data.py already calls successfully.

Sample size caveat: two teams may only play each other 3-19 times a
season (fewer if interleague). Real signal, small sample — the
adjustment is deliberately damped.
"""

import requests

ESPN_TEAM_SCHEDULE_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{team_id}/schedule"


def get_h2h_record(team_id: str, team_name: str, opponent_name: str) -> dict:
    """
    Pulls team_id's completed games this season against opponent_name.
    Returns {"games": int, "wins": int, "losses": int} or all-zero
    dict if the API call fails or no matchups found yet.
    """
    empty = {"games": 0, "wins": 0, "losses": 0}

    url = ESPN_TEAM_SCHEDULE_URL.format(team_id=team_id)
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  H2H fetch error ({team_name}): {e}")
        return empty

    record = dict(empty)
    for event in data.get("events", []):
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
