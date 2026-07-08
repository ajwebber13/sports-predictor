"""
test_officials_endpoint.py — one-off test, not part of the pipeline.
Checks whether ESPN's officials endpoint actually returns data for WNBA.
Confirmed working for NFL; basketball leagues use the same events/competitions
structure, but this needs a real test before building anything on it.

Usage:
    python test_officials_endpoint.py
"""

import requests

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# Get today's/recent WNBA events to test against
scoreboard = requests.get(
    "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard",
    headers=HEADERS, timeout=10
).json()

events = scoreboard.get("events", [])
if not events:
    print("No WNBA events found today — trying yesterday might help, or just")
    print("hardcode a known event_id from a recent game.")
else:
    for event in events[:3]:
        event_id = event.get("id")
        name = event.get("name", "")
        print(f"\nTesting event {event_id} ({name})...")

        url = f"https://sports.core.api.espn.com/v2/sports/basketball/leagues/wnba/events/{event_id}/competitions/{event_id}/officials"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            print(f"  Status: {r.status_code}")
            if r.status_code == 200:
                data = r.json()
                print(f"  Response: {data}")
            else:
                print(f"  Body: {r.text[:300]}")
        except Exception as e:
            print(f"  Error: {e}")
