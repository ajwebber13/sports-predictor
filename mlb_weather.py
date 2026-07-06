"""
mlb_weather.py - Culture & Pulse Analytics
Live weather data for MLB games — wind and temperature affect ball flight
and run scoring in ways that don't apply to indoor sports.
Requires OPENWEATHER_API_KEY (already in use elsewhere in the project).
"""

import os
import requests

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

# Domed/retractable-roof stadiums — weather doesn't affect games played
# indoors (roof closed is the default assumption for domed stadiums here;
# retractable roofs sometimes open, but treating them as indoor is the
# safer default until game-day roof status can be confirmed live).
DOME_TEAMS = {
    "Tampa Bay Rays",
    "Miami Marlins",
    "Arizona Diamondbacks",
    "Houston Astros",
    "Milwaukee Brewers",
    "Toronto Blue Jays",
    "Texas Rangers",
    "Seattle Mariners",  # retractable, often closed
}

STADIUM_COORDS = {
    "Arizona Diamondbacks":  (33.4453, -112.0667),
    "Athletics":             (37.7516, -122.2005),
    "Atlanta Braves":        (33.8907, -84.4677),
    "Baltimore Orioles":     (39.2838, -76.6217),
    "Boston Red Sox":        (42.3467, -71.0972),
    "Chicago Cubs":          (41.9484, -87.6553),
    "Chicago White Sox":     (41.8299, -87.6338),
    "Cincinnati Reds":       (39.0975, -84.5074),
    "Cleveland Guardians":   (41.4962, -81.6852),
    "Colorado Rockies":      (39.7559, -104.9942),
    "Detroit Tigers":        (42.3390, -83.0485),
    "Houston Astros":        (29.7573, -95.3555),
    "Kansas City Royals":    (39.0517, -94.4803),
    "Los Angeles Angels":    (33.8003, -117.8827),
    "Los Angeles Dodgers":   (34.0739, -118.2400),
    "Miami Marlins":         (25.7781, -80.2196),
    "Milwaukee Brewers":     (43.0280, -87.9712),
    "Minnesota Twins":       (44.9817, -93.2775),
    "New York Mets":         (40.7571, -73.8458),
    "New York Yankees":      (40.8296, -73.9262),
    "Philadelphia Phillies": (39.9061, -75.1665),
    "Pittsburgh Pirates":    (40.4469, -80.0057),
    "San Diego Padres":      (32.7076, -117.1570),
    "San Francisco Giants":  (37.7786, -122.3893),
    "Seattle Mariners":      (47.5914, -122.3325),
    "St. Louis Cardinals":   (38.6226, -90.1928),
    "Tampa Bay Rays":        (27.7683, -82.6534),
    "Texas Rangers":         (32.7473, -97.0842),
    "Toronto Blue Jays":     (43.6414, -79.3894),
    "Washington Nationals":  (38.8730, -77.0074),
}


def get_stadium_weather(home_team: str) -> dict:
    """
    Returns weather at the home stadium, or a neutral dict for domed
    stadiums / missing coordinates / API failures.
    """
    neutral = {"temp_f": 72, "wind_mph": 0, "wind_deg": 0, "conditions": "dome", "is_dome": True}

    if home_team in DOME_TEAMS:
        return neutral

    coords = STADIUM_COORDS.get(home_team)
    if not coords or not OPENWEATHER_API_KEY:
        return {**neutral, "conditions": "unknown", "is_dome": False}

    lat, lon = coords
    try:
        r = requests.get(OPENWEATHER_URL, params={
            "lat": lat, "lon": lon, "appid": OPENWEATHER_API_KEY, "units": "imperial",
        }, timeout=10)
        data = r.json()
        return {
            "temp_f":     data["main"]["temp"],
            "wind_mph":   data["wind"]["speed"],
            "wind_deg":   data["wind"].get("deg", 0),
            "conditions": data["weather"][0]["main"] if data.get("weather") else "unknown",
            "is_dome":    False,
        }
    except Exception as e:
        print(f"  Weather fetch error ({home_team}): {e}")
        return {**neutral, "conditions": "unknown", "is_dome": False}


def get_weather_adj(weather: dict) -> float:
    """
    Converts weather into a run-scoring adjustment multiplier.
    Wind blowing out + heat = more runs (ball carries farther).
    Wind blowing in + cold = fewer runs.
    This is a simplified model — doesn't account for wind DIRECTION
    relative to the specific stadium's orientation, only speed and
    general temp effect. Refine later if backtest data supports it.
    """
    if weather.get("is_dome"):
        return 1.0

    temp = weather.get("temp_f", 72)
    wind = weather.get("wind_mph", 0)

    temp_adj = (temp - 72) * 0.002  # warmer = ball carries slightly more
    wind_adj = (wind / 10) * 0.015 if wind > 5 else 0  # only meaningful above ~5mph

    return round(1.0 + temp_adj + wind_adj, 4)