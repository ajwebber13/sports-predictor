"""
generate_cfb_stadiums.py — Culture & Pulse Analytics
========================================================
ONE-TIME generation script, not part of the live pipeline. Builds a
NCAAF_STADIUMS dict for weather_model.py covering all FBS teams (the
live dict only ever had 14, hand-entered blue-bloods) — see the
2026-09-08 CFB weather scoping audit.

For each team in cfb_data.FBS_TEAM_IDS:
  1. Fetch that team's 2026 schedule from ESPN (already-proven pattern,
     same endpoint used elsewhere in this repo for game_date
     resolution) and find their HOME venue: fullName, address.city/
     state, and ESPN's own indoor:true/false flag (confirmed richer
     than NFL_STADIUMS' hand-classified outdoor/dome/retractable
     scheme — no manual roof-type judgment needed).
  2. Geocode city/state via OpenWeatherMap's free geocoding endpoint
     (same OPENWEATHER_API_KEY weather_model.py already uses) to get
     lat/lon, since ESPN's venue data doesn't include coordinates.
  3. Key the result on the SAME short team name cfb_data.FBS_TEAM_IDS
     already uses — NOT ESPN's mascot-suffixed displayName — so this
     can never repeat the Hawaii/San Jose State/Miami OH naming
     mismatch found earlier: the dict is built FROM the short-name
     keys directly, never copied from ESPN's own naming.

Output: prints a Python dict literal, same shape as weather_model.py's
NFL_STADIUMS, meant to be reviewed and pasted in as NCAAF_STADIUMS
(replacing the 14-team version) — not auto-applied.

Usage:
    python generate_cfb_stadiums.py > cfb_stadiums_output.txt
"""

import os
import sys
import time
import json
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cfb_data import FBS_TEAM_IDS

ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports/football/college-football"
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
SEASON = 2026

# The /teams/{id}/schedule endpoint's venue object does NOT include an
# "indoor" key at all (confirmed by direct inspection) — unlike the
# /scoreboard endpoint, which does. get_home_venue() below therefore
# can't tell dome from outdoor and defaults every team to outdoor.
# Cross-checked the full 118-team output for anything with "Dome" in
# its venue name, then verified each one against the /scoreboard
# endpoint directly (which does expose indoor:true/false) rather than
# trusting the name alone. Only these two came back indoor:true out of
# every FBS venue this run resolved — extend this list if a future
# rerun finds another one, same verification method (name is a lead,
# not proof, since a venue could be indoor without "Dome" in its name).
KNOWN_INDOOR_VENUES = {"JMA Wireless Dome", "Alamodome"}


def get_home_venue(team_id: str) -> dict:
    """Returns {fullName, city, state, indoor} for this team's TRUE home
    stadium, or None if it can't be determined.

    FIXED (found spot-checking before the full run): using the first
    home game's venue picked up neutral-site "home" games — Notre Dame
    resolved to Lambeau Field, Green Bay WI (a real but occasional
    neutral-site "home" game), not Notre Dame Stadium. Now filters out
    neutralSite games, and takes the MAJORITY venue across all
    non-neutral home games rather than just the first — a single
    neutral-site game slipping through the flag wouldn't skew the
    result if the team has multiple real home games logged."""
    try:
        r = requests.get(f"{ESPN_BASE}/teams/{team_id}/schedule", params={"season": SEASON}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  ! schedule fetch failed for team {team_id}: {e}", file=sys.stderr)
        return None

    venue_counts = {}   # venue key -> count
    venue_data = {}      # venue key -> full venue dict
    for event in data.get("events", []):
        comp = event.get("competitions", [{}])[0]
        if comp.get("neutralSite"):
            continue
        competitors = comp.get("competitors", [])
        is_home = any(c.get("homeAway") == "home" and c.get("team", {}).get("id") == team_id
                      for c in competitors)
        if not is_home:
            continue
        venue = comp.get("venue")
        if not venue:
            continue
        address = venue.get("address", {})
        city = address.get("city")
        state = address.get("state")
        if not city or not state:
            continue
        key = venue.get("fullName", "")
        venue_counts[key] = venue_counts.get(key, 0) + 1
        venue_data[key] = {
            "fullName": key,
            "city": city,
            "state": state,
            "indoor": bool(venue.get("indoor", False)),
        }

    if not venue_counts:
        return None
    best_key = max(venue_counts, key=venue_counts.get)
    return venue_data[best_key]


def geocode(city: str, state: str) -> tuple:
    """Returns (lat, lon) or (None, None) if geocoding fails."""
    if not OPENWEATHER_API_KEY:
        return None, None
    try:
        r = requests.get(
            "http://api.openweathermap.org/geo/1.0/direct",
            params={"q": f"{city},{state},US", "limit": 1, "appid": OPENWEATHER_API_KEY},
            timeout=10,
        )
        r.raise_for_status()
        results = r.json()
        if not results:
            return None, None
        return round(results[0]["lat"], 4), round(results[0]["lon"], 4)
    except Exception as e:
        print(f"  ! geocode failed for {city},{state}: {e}", file=sys.stderr)
        return None, None


def main():
    if not OPENWEATHER_API_KEY:
        print("ERROR: OPENWEATHER_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    stadiums = {}
    missing = []
    total = len(FBS_TEAM_IDS)

    for i, (team_name, team_id) in enumerate(FBS_TEAM_IDS.items(), 1):
        print(f"[{i}/{total}] {team_name}...", file=sys.stderr)
        venue = get_home_venue(team_id)
        if not venue:
            missing.append(team_name)
            time.sleep(0.2)
            continue

        lat, lon = geocode(venue["city"], venue["state"])
        if lat is None:
            missing.append(team_name)
            time.sleep(0.2)
            continue

        roof = "dome" if (venue["indoor"] or venue["fullName"] in KNOWN_INDOOR_VENUES) else "outdoor"
        stadiums[team_name] = {
            "lat": lat, "lon": lon, "roof": roof,
            "_venue": venue["fullName"], "_city": venue["city"], "_state": venue["state"],
        }
        time.sleep(0.2)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Resolved {len(stadiums)}/{total} teams. Missing: {missing}", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    print("NCAAF_STADIUMS = {")
    for team_name in FBS_TEAM_IDS:
        if team_name not in stadiums:
            continue
        s = stadiums[team_name]
        print(f'    "{team_name}": {{"lat": {s["lat"]}, "lon": {s["lon"]}, "roof": "{s["roof"]}"}},  '
              f'# {s["_venue"]}, {s["_city"]}, {s["_state"]}')
    print("}")


if __name__ == "__main__":
    main()
