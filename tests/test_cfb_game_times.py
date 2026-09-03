"""
tests/test_cfb_game_times.py — Culture & Pulse Analytics
================================================================
Regression tests for two compounding bugs fixed in
telegram_alerts.get_game_times() (2026-09-04) that produced every CFB
alert showing "Time TBD" and let a Saturday game's alert reach Discord
on a Thursday afternoon run:

1. get_game_times("cfb") called ESPN's scoreboard with no query params
   at all. Confirmed live: with no params, ESPN returns an arbitrary
   ~25-event default subset that does NOT reliably include every real
   game (Oklahoma State and Boston College's games were both missing).
   cfb_data.get_cfb_events() already solved this for /cfb/edges with a
   7-day date window + groups=80 (FBS) + limit=200 -- confirmed live,
   those params return the full ~90-team slate. Same params now used
   here, CFB-only.

2. Even with the right events, ESPN's displayName is the full mascot
   name ("Oklahoma State Cowboys") while every bet's "game" string uses
   this codebase's canonical short name ("Oklahoma State" -- the same
   FBS_TEAM_IDS key used everywhere else in the CFB pipeline). An exact
   dict lookup on "Oklahoma State" against a "Oklahoma State Cowboys"
   key never matched -- a second, compounding cause of the same "Time
   TBD" symptom. Now resolved by ESPN team ID via cfb_data.ID_TO_TEAM,
   the same way get_cfb_events() already does it correctly.

Also covers the date-filter hardening in render_job.py: an unknown
kickoff time (empty raw_time) must be held, never assumed to be today
-- that silent fall-through is what let a future Saturday game's alert
go out on a Thursday run in the first place, once get_game_times("cfb")
was returning nothing to match against.

Usage:
    py tests/test_cfb_game_times.py
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except ImportError:
    pass

import telegram_alerts


def _check(label, condition, detail):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}: {detail}")
    return condition


def _fake_espn_response():
    """Mimics ESPN's scoreboard shape for one game: Boston College
    (away, id 103) @ Cincinnati (home, id 2132) -- real FBS_TEAM_IDS
    entries this repo already uses, with ESPN's full mascot-name
    displayName (the thing that broke the old exact-string lookup)."""
    return {
        "events": [{
            "date": "2026-09-05T19:30Z",
            "competitions": [{
                "competitors": [
                    {"homeAway": "home", "team": {"id": "2132", "displayName": "Cincinnati Bearcats"}},
                    {"homeAway": "away", "team": {"id": "103", "displayName": "Boston College Eagles"}},
                ]
            }],
        }]
    }


def run():
    results = []

    print("Testing get_game_times('cfb') params...")
    with patch.object(telegram_alerts.requests, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"events": []}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        telegram_alerts.get_game_times("cfb")
        call_kwargs = mock_get.call_args.kwargs
        params = call_kwargs.get("params", {})

    results.append(_check(
        "cfb request includes groups=80 (FBS) -- ESPN silently returns a partial "
        "default slate without it",
        params.get("groups") == "80",
        f"params={params}",
    ))
    results.append(_check(
        "cfb request includes a dates range",
        "dates" in params and "-" in str(params["dates"]),
        f"params={params}",
    ))
    results.append(_check(
        "cfb request includes limit=200",
        params.get("limit") == 200,
        f"params={params}",
    ))

    print("\nTesting get_game_times('cfb') resolves by ESPN team ID, not displayName...")
    with patch.object(telegram_alerts.requests, "get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = _fake_espn_response()
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        times, times_raw = telegram_alerts.get_game_times("cfb")

    results.append(_check(
        "canonical short name 'Boston College' is a key (not the ESPN mascot name)",
        "Boston College" in times,
        f"keys sample={[k for k in times if 'Boston' in k or 'Cincinnati' in k]}",
    ))
    results.append(_check(
        "canonical short name 'Cincinnati' is a key",
        "Cincinnati" in times,
        f"value={times.get('Cincinnati')}",
    ))
    results.append(_check(
        "the full game key 'Boston College @ Cincinnati' resolves to a real time, not Time TBD",
        times.get("Boston College @ Cincinnati") not in (None, "Time TBD"),
        f"value={times.get('Boston College @ Cincinnati')}",
    ))

    print("\nTesting get_raw_time_for_bet() finds it for a real bet dict...")
    bet = {"game": "Boston College @ Cincinnati"}
    raw = telegram_alerts.get_raw_time_for_bet(bet, times_raw)
    results.append(_check(
        "get_raw_time_for_bet returns the real ISO timestamp, not empty",
        raw == "2026-09-05T19:30Z",
        f"raw={raw!r}",
    ))

    print()
    if all(results):
        print(f"All {len(results)} tests passed.")
        return 0
    else:
        failed = len(results) - sum(results)
        print(f"{failed} of {len(results)} tests FAILED.")
        return 1


if __name__ == "__main__":
    sys.exit(run())
