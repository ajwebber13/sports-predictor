"""
debug_h2h_matchup.py
One-off diagnostic — dumps real payload shapes for the two things
that came back all-zero: H2H (ESPN team schedule) and matchup
(MLB Stats API). Same pattern as debug_dump_pitcher_keys.py.

Usage:
  python debug_h2h_matchup.py
"""

import requests
import json

# ── H2H: dump one real division-rival schedule event ──
# Boston Red Sox (ESPN team id 2) vs Baltimore Orioles (ESPN team id 1)
print("=" * 60)
print("H2H — Boston Red Sox schedule (looking for an Orioles game)")
print("=" * 60)

url = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/2/schedule"
r = requests.get(url, timeout=10)
data = r.json()

found = False
for event in data.get("events", []):
    comp = event.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    names = [c.get("team", {}).get("displayName", "") for c in competitors]
    if "Baltimore Orioles" in names:
        found = True
        print(f"\nEvent date: {event.get('date')}")
        print(f"Status completed: {comp.get('status', {}).get('type', {}).get('completed')}")
        print("Raw competitors block:")
        print(json.dumps(competitors, indent=2)[:3000])
        break

if not found:
    print("No Orioles game found in Red Sox schedule at all — dumping first event's raw shape instead:")
    if data.get("events"):
        print(json.dumps(data["events"][0], indent=2)[:3000])

# ── Matchup: dump pitcher search + team-vs-pitcher stats ──
print("\n" + "=" * 60)
print("MATCHUP — pitcher search + team-vs-pitcher stats")
print("=" * 60)

# Use a real, well-known active pitcher name as the test case
test_pitcher_name = "Gerrit Cole"
search_url = "https://statsapi.mlb.com/api/v1/people/search"
r2 = requests.get(search_url, params={"names": test_pitcher_name}, timeout=10)
print(f"\nSearch status code: {r2.status_code}")
search_data = r2.json()
print("Raw search response:")
print(json.dumps(search_data, indent=2)[:2000])

people = search_data.get("people", [])
if people:
    pitcher_id = people[0].get("id")
    print(f"\nFound pitcher ID: {pitcher_id}")

    # New York Yankees team id (MLB Stats API) = 147
    stats_url = f"https://statsapi.mlb.com/api/v1/teams/147/stats"
    r3 = requests.get(stats_url, params={
        "stats": "vsPlayer", "opposingPlayerId": pitcher_id, "group": "hitting",
    }, timeout=10)
    print(f"\nTeam-vs-pitcher stats status code: {r3.status_code}")
    print("Raw stats response:")
    print(json.dumps(r3.json(), indent=2)[:3000])
else:
    print("\nNo people found in search — search endpoint/param name is likely wrong.")
