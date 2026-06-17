"""
weather_model.py - Culture & Pulse Analytics
Pulls live weather forecasts for outdoor NFL and NCAAF games
and calculates scoring/passing impact adjustments.

Indoor/dome stadiums are automatically skipped - weather has
no impact when the roof is closed.

Requires a free OpenWeatherMap API key:
  https://openweathermap.org/api
  Set as env var: OPENWEATHER_API_KEY

Usage:
  python weather_model.py check nfl "Buffalo Bills"
  python weather_model.py check ncaaf "Ohio State Buckeyes"
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
OPENWEATHER_BASE     = "https://api.openweathermap.org/data/2.5/forecast"


# ─────────────────────────────────────────────────────────────
# STADIUM DATA - location + roof type for all 32 NFL teams
# Roof types: "outdoor", "dome", "retractable"
# Retractable roofs are treated as dome (closed) by default
# since most teams close them in bad weather anyway.
# ─────────────────────────────────────────────────────────────

NFL_STADIUMS = {
    "Arizona Cardinals":        {"lat": 33.5276, "lon": -112.2626, "roof": "retractable"},
    "Atlanta Falcons":          {"lat": 33.7553, "lon": -84.4006,  "roof": "dome"},
    "Baltimore Ravens":         {"lat": 39.2780, "lon": -76.6227,  "roof": "outdoor"},
    "Buffalo Bills":            {"lat": 42.7738, "lon": -78.7870,  "roof": "outdoor"},
    "Carolina Panthers":        {"lat": 35.2258, "lon": -80.8528,  "roof": "outdoor"},
    "Chicago Bears":            {"lat": 41.8623, "lon": -87.6167,  "roof": "outdoor"},
    "Cincinnati Bengals":       {"lat": 39.0954, "lon": -84.5160,  "roof": "outdoor"},
    "Cleveland Browns":         {"lat": 41.5061, "lon": -81.6995,  "roof": "outdoor"},
    "Dallas Cowboys":           {"lat": 32.7473, "lon": -97.0945,  "roof": "retractable"},
    "Denver Broncos":           {"lat": 39.7439, "lon": -105.0201, "roof": "outdoor"},
    "Detroit Lions":            {"lat": 42.3400, "lon": -83.0456,  "roof": "dome"},
    "Green Bay Packers":        {"lat": 44.5013, "lon": -88.0622,  "roof": "outdoor"},
    "Houston Texans":           {"lat": 29.6847, "lon": -95.4107,  "roof": "retractable"},
    "Indianapolis Colts":       {"lat": 39.7601, "lon": -86.1639,  "roof": "retractable"},
    "Jacksonville Jaguars":     {"lat": 30.3239, "lon": -81.6373,  "roof": "outdoor"},
    "Kansas City Chiefs":       {"lat": 39.0489, "lon": -94.4839,  "roof": "outdoor"},
    "Las Vegas Raiders":        {"lat": 36.0909, "lon": -115.1833, "roof": "dome"},
    "Los Angeles Chargers":     {"lat": 33.9535, "lon": -118.3392, "roof": "dome"},
    "Los Angeles Rams":         {"lat": 33.9535, "lon": -118.3392, "roof": "dome"},
    "Miami Dolphins":           {"lat": 25.9580, "lon": -80.2389,  "roof": "outdoor"},
    "Minnesota Vikings":        {"lat": 44.9737, "lon": -93.2581,  "roof": "dome"},
    "New England Patriots":     {"lat": 42.0909, "lon": -71.2643,  "roof": "outdoor"},
    "New Orleans Saints":       {"lat": 29.9511, "lon": -90.0812,  "roof": "dome"},
    "New York Giants":          {"lat": 40.8128, "lon": -74.0742,  "roof": "outdoor"},
    "New York Jets":            {"lat": 40.8128, "lon": -74.0742,  "roof": "outdoor"},
    "Philadelphia Eagles":      {"lat": 39.9008, "lon": -75.1675,  "roof": "outdoor"},
    "Pittsburgh Steelers":      {"lat": 40.4468, "lon": -80.0158,  "roof": "outdoor"},
    "San Francisco 49ers":      {"lat": 37.4032, "lon": -121.9698, "roof": "outdoor"},
    "Seattle Seahawks":         {"lat": 47.5952, "lon": -122.3316, "roof": "outdoor"},
    "Tampa Bay Buccaneers":     {"lat": 27.9759, "lon": -82.5033,  "roof": "outdoor"},
    "Tennessee Titans":         {"lat": 36.1665, "lon": -86.7713,  "roof": "outdoor"},
    "Washington Commanders":    {"lat": 38.9077, "lon": -76.8644,  "roof": "outdoor"},
}

# Common NCAAF stadium locations - expand as needed.
# Nearly all college football is outdoor, so this list is smaller
# and we default unknown teams to "outdoor" since that's the vast majority.
NCAAF_STADIUMS = {
    "Ohio State Buckeyes":       {"lat": 40.0017, "lon": -83.0197,  "roof": "outdoor"},
    "Michigan Wolverines":       {"lat": 42.2658, "lon": -83.7487,  "roof": "outdoor"},
    "Alabama Crimson Tide":      {"lat": 33.2083, "lon": -87.5503,  "roof": "outdoor"},
    "Georgia Bulldogs":          {"lat": 33.9497, "lon": -83.3733,  "roof": "outdoor"},
    "Texas Longhorns":           {"lat": 30.2839, "lon": -97.7325,  "roof": "outdoor"},
    "Oklahoma Sooners":          {"lat": 35.2058, "lon": -97.4423,  "roof": "outdoor"},
    "Notre Dame Fighting Irish": {"lat": 41.6989, "lon": -86.2347,  "roof": "outdoor"},
    "Penn State Nittany Lions":  {"lat": 40.8122, "lon": -77.8561,  "roof": "outdoor"},
    "Oregon Ducks":              {"lat": 44.0582, "lon": -123.0686, "roof": "outdoor"},
    "LSU Tigers":                {"lat": 30.4118, "lon": -91.1837,  "roof": "outdoor"},
    "Clemson Tigers":            {"lat": 34.6786, "lon": -82.8434,  "roof": "outdoor"},
    "USC Trojans":               {"lat": 34.0141, "lon": -118.2879, "roof": "outdoor"},
    "Washington Huskies":        {"lat": 47.6503, "lon": -122.3017, "roof": "outdoor"},
    "Miami Hurricanes":          {"lat": 25.9580, "lon": -80.2389,  "roof": "outdoor"},
}


def is_dome(team_name: str, sport: str = "nfl") -> bool:
    """Returns True if the team plays in a dome/retractable (closed) stadium."""
    stadiums = NFL_STADIUMS if sport == "nfl" else NCAAF_STADIUMS
    info     = stadiums.get(team_name)
    if not info:
        return False  # default outdoor for unknown teams (especially NCAAF)
    return info["roof"] in ("dome", "retractable")


def get_stadium_location(team_name: str, sport: str = "nfl") -> dict:
    stadiums = NFL_STADIUMS if sport == "nfl" else NCAAF_STADIUMS
    return stadiums.get(team_name)


def fetch_weather_forecast(lat: float, lon: float) -> dict:
    """
    Pulls the nearest forecast window from OpenWeatherMap.
    Returns dict with temp (F), wind_mph, precipitation chance, condition.
    """
    if not OPENWEATHER_API_KEY:
        return {}

    try:
        resp = requests.get(OPENWEATHER_BASE, params={
            "lat":   lat,
            "lon":   lon,
            "appid": OPENWEATHER_API_KEY,
            "units": "imperial",
        }, timeout=10)
        data = resp.json()
        forecasts = data.get("list", [])
        if not forecasts:
            return {}

        # Use the nearest forecast window (3-hour increments)
        nearest = forecasts[0]
        main    = nearest.get("main", {})
        wind    = nearest.get("wind", {})
        weather = nearest.get("weather", [{}])[0]
        pop     = nearest.get("pop", 0.0)  # probability of precipitation

        return {
            "temp_f":     round(main.get("temp", 70.0), 1),
            "wind_mph":   round(wind.get("speed", 0.0), 1),
            "condition":  weather.get("main", "Clear"),
            "description": weather.get("description", ""),
            "precip_chance": round(pop * 100, 0),
        }
    except Exception as e:
        print(f"  Weather fetch error: {e}")
        return {}


def calculate_weather_adjustment(weather: dict) -> dict:
    """
    Converts raw weather data into scoring/passing adjustments.

    Returns:
      total_pts_adj   - point adjustment applied to projected total
      passing_penalty - extra penalty applied to passing offenses specifically
      summary         - human readable explanation
    """
    if not weather:
        return {"total_pts_adj": 0.0, "passing_penalty": 0.0, "summary": "No weather data"}

    temp   = weather.get("temp_f", 70.0)
    wind   = weather.get("wind_mph", 0.0)
    precip = weather.get("precip_chance", 0.0)
    cond   = weather.get("condition", "Clear")

    total_adj    = 0.0
    pass_penalty = 0.0
    notes        = []

    # Wind impact - significantly affects passing and kicking
    if wind >= 20:
        total_adj    -= 4.0
        pass_penalty -= 0.15
        notes.append(f"High wind ({wind} mph) — major passing/kicking impact")
    elif wind >= 15:
        total_adj    -= 2.5
        pass_penalty -= 0.08
        notes.append(f"Moderate wind ({wind} mph) — passing impact")
    elif wind >= 10:
        total_adj    -= 1.0
        pass_penalty -= 0.03
        notes.append(f"Light wind ({wind} mph) — minor impact")

    # Cold weather impact
    if temp <= 20:
        total_adj -= 3.0
        notes.append(f"Extreme cold ({temp}°F) — ball handling, kicking affected")
    elif temp <= 32:
        total_adj -= 1.5
        notes.append(f"Freezing temps ({temp}°F) — moderate impact")

    # Precipitation impact
    if precip >= 70 or cond in ("Rain", "Snow", "Thunderstorm"):
        total_adj    -= 2.5
        pass_penalty -= 0.10
        notes.append(f"{cond} likely ({precip}% chance) — ball security, footing affected")
    elif precip >= 40:
        total_adj    -= 1.0
        notes.append(f"Possible {cond.lower()} ({precip}% chance)")

    summary = "; ".join(notes) if notes else "Clear conditions — no significant impact"

    return {
        "total_pts_adj":   round(total_adj, 1),
        "passing_penalty": round(pass_penalty, 3),
        "summary": summary,
    }


def get_game_weather_impact(home_team: str, sport: str = "nfl") -> dict:
    """
    Main entry point. Checks if the stadium is a dome first
    (skips weather entirely if so), otherwise fetches live
    forecast and returns the scoring adjustment.
    """
    if is_dome(home_team, sport):
        return {
            "total_pts_adj":   0.0,
            "passing_penalty": 0.0,
            "summary": "Indoor/dome stadium — no weather impact",
            "is_dome": True,
        }

    location = get_stadium_location(home_team, sport)
    if not location:
        return {
            "total_pts_adj":   0.0,
            "passing_penalty": 0.0,
            "summary": "Stadium location unknown — no adjustment applied",
            "is_dome": False,
        }

    weather = fetch_weather_forecast(location["lat"], location["lon"])
    if not weather:
        return {
            "total_pts_adj":   0.0,
            "passing_penalty": 0.0,
            "summary": "Weather data unavailable",
            "is_dome": False,
        }

    adjustment = calculate_weather_adjustment(weather)
    adjustment["is_dome"]  = False
    adjustment["raw"]      = weather
    return adjustment


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "check":
        sport = sys.argv[2].lower()
        team  = sys.argv[3]

        if not OPENWEATHER_API_KEY:
            print("No OPENWEATHER_API_KEY set. Add it to your .env file.")
            sys.exit(1)

        result = get_game_weather_impact(team, sport)
        print(f"\nWeather check: {team} ({sport.upper()})")
        print(f"{'='*50}")
        if result.get("is_dome"):
            print("Indoor/dome stadium — weather has no impact")
        else:
            raw = result.get("raw", {})
            if raw:
                print(f"Temp: {raw.get('temp_f')}°F")
                print(f"Wind: {raw.get('wind_mph')} mph")
                print(f"Condition: {raw.get('description')}")
                print(f"Precip chance: {raw.get('precip_chance')}%")
            print(f"\nTotal points adjustment: {result['total_pts_adj']}")
            print(f"Passing penalty: {result['passing_penalty']}")
            print(f"Summary: {result['summary']}")
        print(f"{'='*50}\n")
    else:
        print("Usage: python weather_model.py check [nfl|ncaaf] \"Team Name\"")
