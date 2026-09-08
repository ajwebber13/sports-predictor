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

# FBS stadium locations, keyed on the SAME short team names
# cfb_data.FBS_TEAM_IDS uses (matches CFBTeamStats.team_name directly —
# deliberately NOT ESPN's mascot-suffixed displayName, the exact
# mismatch class that silently broke Hawaii/San Jose State/Miami OH
# grading earlier). Generated 2026-09-08 via generate_cfb_stadiums.py:
# venue name/city/state/indoor pulled from ESPN's team-schedule
# endpoint (majority vote across each team's non-neutral-site home
# games, to avoid picking up an occasional true neutral-site "home"
# game — Notre Dame's script output briefly resolved to Lambeau Field
# before that fix), lat/lon from OpenWeatherMap's geocoding endpoint.
#
# roof: ESPN's schedule endpoint doesn't expose an indoor flag at all
# (only the /scoreboard endpoint does) — ALL 122 teams came back
# "outdoor" from that field defaulting False. Cross-checked every venue
# with "Dome" in its name against /scoreboard directly (which does
# expose indoor:true/false) rather than trusting the name alone; only
# Syracuse (JMA Wireless Dome) and UTSA (Alamodome) confirmed indoor
# out of all 122 — extend KNOWN_INDOOR_VENUES in the generation script
# if a future rerun finds another.
#
# 119/122 resolved. 3 not included, pre-existing cfb_data.py issues
# unrelated to weather: James Madison and New Mexico State's ESPN team
# IDs 400 on the schedule endpoint (likely stale/wrong IDs in
# FBS_TEAM_IDS); Wichita State returned zero 2026 events (their
# football program was discontinued in 1986 — shouldn't be in
# FBS_TEAM_IDS at all). Air Force's venue resolved correctly but
# "USAF Academy" isn't a recognized city in OpenWeatherMap's geocoder —
# manually substituted Colorado Springs' coordinates (~10mi off the
# actual stadium, acceptable for regional forecast purposes).
NCAAF_STADIUMS = {
    "Alabama": {"lat": 33.2096, "lon": -87.5675, "roof": "outdoor"},  # Bryant-Denny Stadium, Tuscaloosa, AL
    "Arkansas": {"lat": 36.0626, "lon": -94.1574, "roof": "outdoor"},  # Donald W. Reynolds Razorback Stadium, Fayetteville, AR
    "Auburn": {"lat": 32.6099, "lon": -85.4808, "roof": "outdoor"},  # Jordan-Hare Stadium, Auburn, AL
    "Florida": {"lat": 29.652, "lon": -82.325, "roof": "outdoor"},  # Ben Hill Griffin Stadium, Gainesville, FL
    "Georgia": {"lat": 33.9598, "lon": -83.3764, "roof": "outdoor"},  # Sanford Stadium, Athens, GA
    "Kentucky": {"lat": 38.0464, "lon": -84.497, "roof": "outdoor"},  # Kroger Field, Lexington, KY
    "LSU": {"lat": 30.4494, "lon": -91.187, "roof": "outdoor"},  # Tiger Stadium (LA), Baton Rouge, LA
    "Mississippi State": {"lat": 33.4639, "lon": -88.8152, "roof": "outdoor"},  # Davis Wade Stadium, Starkville, MS
    "Missouri": {"lat": 38.9519, "lon": -92.3337, "roof": "outdoor"},  # Memorial Stadium, Columbia, MO
    "Ole Miss": {"lat": 34.3664, "lon": -89.5188, "roof": "outdoor"},  # Vaught-Hemingway Stadium, Oxford, MS
    "South Carolina": {"lat": 34.0008, "lon": -81.0352, "roof": "outdoor"},  # Williams-Brice Stadium, Columbia, SC
    "Tennessee": {"lat": 35.9604, "lon": -83.921, "roof": "outdoor"},  # Neyland Stadium, Knoxville, TN
    "Texas": {"lat": 30.2711, "lon": -97.7437, "roof": "outdoor"},  # DKR-Texas Memorial Stadium, Austin, TX
    "Texas A&M": {"lat": 30.6184, "lon": -96.3456, "roof": "outdoor"},  # Kyle Field, College Station, TX
    "Vanderbilt": {"lat": 36.1623, "lon": -86.7743, "roof": "outdoor"},  # FirstBank Stadium, Nashville, TN
    "Oklahoma": {"lat": 35.2226, "lon": -97.4395, "roof": "outdoor"},  # Memorial Stadium (Norman, OK), Norman, OK
    "Illinois": {"lat": 40.1165, "lon": -88.2431, "roof": "outdoor"},  # Gies Memorial Stadium, Champaign, IL
    "Indiana": {"lat": 39.167, "lon": -86.5343, "roof": "outdoor"},  # Memorial Stadium (Bloomington, IN), Bloomington, IN
    "Iowa": {"lat": 41.6613, "lon": -91.5299, "roof": "outdoor"},  # Kinnick Stadium, Iowa City, IA
    "Maryland": {"lat": 38.9807, "lon": -76.9369, "roof": "outdoor"},  # SECU Stadium, College Park, MD
    "Michigan": {"lat": 42.2814, "lon": -83.7485, "roof": "outdoor"},  # Michigan Stadium, Ann Arbor, MI
    "Michigan State": {"lat": 42.732, "lon": -84.4722, "roof": "outdoor"},  # Spartan Stadium, East Lansing, MI
    "Minnesota": {"lat": 44.9773, "lon": -93.2655, "roof": "outdoor"},  # Huntington Bank Stadium, Minneapolis, MN
    "Nebraska": {"lat": 40.8089, "lon": -96.7078, "roof": "outdoor"},  # Memorial Stadium (Lincoln, NE), Lincoln, NE
    "Northwestern": {"lat": 42.047, "lon": -87.6846, "roof": "outdoor"},  # Ryan Field, Evanston, IL
    "Ohio State": {"lat": 39.9623, "lon": -83.0007, "roof": "outdoor"},  # Ohio Stadium, Columbus, OH
    "Oregon": {"lat": 44.0505, "lon": -123.0951, "roof": "outdoor"},  # Autzen Stadium, Eugene, OR
    "Penn State": {"lat": 34.7406, "lon": -86.623, "roof": "outdoor"},  # Beaver Stadium, University Park, PA
    "Purdue": {"lat": 40.4259, "lon": -86.9081, "roof": "outdoor"},  # Ross-Ade Stadium, West Lafayette, IN
    "Rutgers": {"lat": 40.5463, "lon": -74.466, "roof": "outdoor"},  # SHI Stadium, Piscataway, NJ
    "UCLA": {"lat": 34.1477, "lon": -118.1442, "roof": "outdoor"},  # Rose Bowl, Pasadena, CA
    "USC": {"lat": 34.0537, "lon": -118.2428, "roof": "outdoor"},  # Los Angeles Memorial Coliseum, Los Angeles, CA
    "Washington": {"lat": 47.6038, "lon": -122.3301, "roof": "outdoor"},  # Husky Stadium, Seattle, WA
    "Wisconsin": {"lat": 43.0748, "lon": -89.3838, "roof": "outdoor"},  # Camp Randall Stadium, Madison, WI
    "Boston College": {"lat": 42.3307, "lon": -71.1662, "roof": "outdoor"},  # Alumni Stadium (Chestnut Hill, MA), Chestnut Hill, MA
    "California": {"lat": 37.8708, "lon": -122.2729, "roof": "outdoor"},  # California Memorial Stadium, Berkeley, CA
    "Clemson": {"lat": 34.6851, "lon": -82.8364, "roof": "outdoor"},  # Memorial Stadium (Clemson, SC), Clemson, SC
    "Duke": {"lat": 35.9967, "lon": -78.9018, "roof": "outdoor"},  # Wallace Wade Stadium, Durham, NC
    "Florida State": {"lat": 30.4381, "lon": -84.2809, "roof": "outdoor"},  # Doak Campbell Stadium, Tallahassee, FL
    "Georgia Tech": {"lat": 33.749, "lon": -84.3903, "roof": "outdoor"},  # Bobby Dodd Stadium, Atlanta, GA
    "Louisville": {"lat": 38.2542, "lon": -85.7594, "roof": "outdoor"},  # L&N Federal Credit Union Stadium, Louisville, KY
    "Miami": {"lat": 25.942, "lon": -80.2456, "roof": "outdoor"},  # Hard Rock Stadium, Miami Gardens, FL
    "NC State": {"lat": 35.7804, "lon": -78.6391, "roof": "outdoor"},  # Carter-Finley Stadium, Raleigh, NC
    "North Carolina": {"lat": 35.9132, "lon": -79.0558, "roof": "outdoor"},  # Kenan Stadium, Chapel Hill, NC
    "Pittsburgh": {"lat": 40.4417, "lon": -79.9901, "roof": "outdoor"},  # Acrisure Stadium, Pittsburgh, PA
    "SMU": {"lat": 32.7763, "lon": -96.7969, "roof": "outdoor"},  # Gerald J. Ford Stadium, Dallas, TX
    "Stanford": {"lat": 37.4275, "lon": -122.1702, "roof": "outdoor"},  # Stanford Stadium, Stanford, CA
    "Syracuse": {"lat": 43.0481, "lon": -76.1474, "roof": "dome"},  # JMA Wireless Dome, Syracuse, NY
    "Virginia": {"lat": 38.0293, "lon": -78.4767, "roof": "outdoor"},  # Scott Stadium, Charlottesville, VA
    "Virginia Tech": {"lat": 37.2297, "lon": -80.4137, "roof": "outdoor"},  # Lane Stadium, Blacksburg, VA
    "Wake Forest": {"lat": 36.0998, "lon": -80.2441, "roof": "outdoor"},  # Allegacy Federal Credit Union Stadium, Winston-Salem, NC
    "Arizona": {"lat": 32.2229, "lon": -110.9748, "roof": "outdoor"},  # Casino Del Sol Stadium, Tucson, AZ
    "Arizona State": {"lat": 33.4255, "lon": -111.94, "roof": "outdoor"},  # Mountain America Stadium, Tempe, AZ
    "Baylor": {"lat": 31.5492, "lon": -97.1475, "roof": "outdoor"},  # McLane Stadium, Waco, TX
    "BYU": {"lat": 40.2337, "lon": -111.6587, "roof": "outdoor"},  # LaVell Edwards Stadium, Provo, UT
    "Cincinnati": {"lat": 39.1015, "lon": -84.5125, "roof": "outdoor"},  # Nippert Stadium, Cincinnati, OH
    "Colorado": {"lat": 40.015, "lon": -105.2705, "roof": "outdoor"},  # Folsom Field, Boulder, CO
    "Houston": {"lat": 29.7589, "lon": -95.3677, "roof": "outdoor"},  # TDECU Stadium, Houston, TX
    "Iowa State": {"lat": 42.0268, "lon": -93.617, "roof": "outdoor"},  # Jack Trice Stadium, Ames, IA
    "Kansas": {"lat": 38.9719, "lon": -95.2359, "roof": "outdoor"},  # David Booth Kansas Memorial Stadium, Lawrence, KS
    "Kansas State": {"lat": 39.1836, "lon": -96.5717, "roof": "outdoor"},  # Bill Snyder Family Stadium, Manhattan, KS
    "Oklahoma State": {"lat": 36.1156, "lon": -97.0586, "roof": "outdoor"},  # Boone Pickens Stadium, Stillwater, OK
    "TCU": {"lat": 32.7532, "lon": -97.3327, "roof": "outdoor"},  # Amon G. Carter Stadium, Fort Worth, TX
    "Texas Tech": {"lat": 33.5856, "lon": -101.847, "roof": "outdoor"},  # Jones AT&T / Lubbock, TX venue, Lubbock, TX
    "UCF": {"lat": 28.5421, "lon": -81.379, "roof": "outdoor"},  # Acrisure Bounce House, Orlando, FL
    "Utah": {"lat": 40.7596, "lon": -111.8868, "roof": "outdoor"},  # Rice-Eccles Stadium, Salt Lake City, UT
    "West Virginia": {"lat": 39.6297, "lon": -79.9559, "roof": "outdoor"},  # Milan Puskar Stadium, Morgantown, WV
    "Charlotte": {"lat": 35.2272, "lon": -80.8431, "roof": "outdoor"},  # Jerry Richardson Stadium, Charlotte, NC
    "East Carolina": {"lat": 35.6132, "lon": -77.3725, "roof": "outdoor"},  # Dowdy-Ficklen Stadium, Greenville, NC
    "Florida Atlantic": {"lat": 26.3587, "lon": -80.0831, "roof": "outdoor"},  # Flagler Credit Union Stadium, Boca Raton, FL
    "Memphis": {"lat": 35.146, "lon": -90.0518, "roof": "outdoor"},  # Simmons Bank Liberty Stadium, Memphis, TN
    "Navy": {"lat": 38.9786, "lon": -76.4928, "roof": "outdoor"},  # Navy-Marine Corps Memorial Stadium, Annapolis, MD
    "North Texas": {"lat": 33.215, "lon": -97.1331, "roof": "outdoor"},  # DATCU Stadium, Denton, TX
    "Rice": {"lat": 29.7589, "lon": -95.3677, "roof": "outdoor"},  # Rice Stadium, Houston, TX
    "South Florida": {"lat": 27.9478, "lon": -82.4584, "roof": "outdoor"},  # Raymond James Stadium, Tampa, FL
    "Temple": {"lat": 39.9527, "lon": -75.1635, "roof": "outdoor"},  # Lincoln Financial Field, Philadelphia, PA
    "Tulane": {"lat": 29.976, "lon": -90.0782, "roof": "outdoor"},  # Yulman Stadium, New Orleans, LA
    "Tulsa": {"lat": 36.1563, "lon": -95.9928, "roof": "outdoor"},  # H. A. Chapman Stadium, Tulsa, OK
    "UTSA": {"lat": 29.4246, "lon": -98.4951, "roof": "dome"},  # Alamodome, San Antonio, TX
    "Air Force": {"lat": 38.834, "lon": -104.8253, "roof": "outdoor"},  # Falcon Stadium, USAF Academy, CO (geocoded to Colorado Springs)
    "Boise State": {"lat": 43.6166, "lon": -116.2009, "roof": "outdoor"},  # Albertsons Stadium, Boise, ID
    "Colorado State": {"lat": 40.5872, "lon": -105.077, "roof": "outdoor"},  # Canvas Stadium, Fort Collins, CO
    "Fresno State": {"lat": 36.7394, "lon": -119.7848, "roof": "outdoor"},  # Valley Children's Stadium, Fresno, CA
    "Hawaii": {"lat": 21.3045, "lon": -157.8557, "roof": "outdoor"},  # Clarence T.C. Ching Athletics Complex, Honolulu, HI
    "Nevada": {"lat": 39.5261, "lon": -119.8127, "roof": "outdoor"},  # Mackay Stadium, Reno, NV
    "New Mexico": {"lat": 35.0841, "lon": -106.651, "roof": "outdoor"},  # University Stadium (NM), Albuquerque, NM
    "San Diego State": {"lat": 32.7174, "lon": -117.1628, "roof": "outdoor"},  # Snapdragon Stadium, San Diego, CA
    "San Jose State": {"lat": 37.3362, "lon": -121.8906, "roof": "outdoor"},  # CEFCU Stadium, San Jose, CA
    "UNLV": {"lat": 36.1673, "lon": -115.1484, "roof": "outdoor"},  # Allegiant Stadium, Las Vegas, NV
    "Utah State": {"lat": 41.7313, "lon": -111.8349, "roof": "outdoor"},  # Maverik Stadium, Logan, UT
    "Wyoming": {"lat": 41.3116, "lon": -105.5918, "roof": "outdoor"},  # War Memorial Stadium, Laramie, WY
    "App State": {"lat": 36.2188, "lon": -81.684, "roof": "outdoor"},  # Kidd Brewer Stadium, Boone, NC
    "Arkansas State": {"lat": 35.8272, "lon": -90.695, "roof": "outdoor"},  # Centennial Bank Stadium, Jonesboro, AR
    "Coastal Carolina": {"lat": 33.836, "lon": -79.0478, "roof": "outdoor"},  # Brooks Stadium (SC), Conway, SC
    "Georgia Southern": {"lat": 32.449, "lon": -81.7833, "roof": "outdoor"},  # Allen E. Paulson Stadium, Statesboro, GA
    "Georgia State": {"lat": 33.749, "lon": -84.3903, "roof": "outdoor"},  # Center Parc Stadium, Atlanta, GA
    "Louisiana": {"lat": 30.2262, "lon": -92.0178, "roof": "outdoor"},  # Our Lady of Lourdes Stadium, Lafayette, LA
    "Louisiana Monroe": {"lat": 32.5025, "lon": -92.1162, "roof": "outdoor"},  # Malone Stadium, Monroe, LA
    "Marshall": {"lat": 38.4192, "lon": -82.4452, "roof": "outdoor"},  # Joan C. Edwards Stadium, Huntington, WV
    "Old Dominion": {"lat": 36.8494, "lon": -76.29, "roof": "outdoor"},  # S.B. Ballard Stadium, Norfolk, VA
    "South Alabama": {"lat": 30.6913, "lon": -88.0438, "roof": "outdoor"},  # Hancock Whitney Stadium, Mobile, AL
    "Southern Miss": {"lat": 31.3271, "lon": -89.2903, "roof": "outdoor"},  # M. M. Roberts Stadium, Hattiesburg, MS
    "Texas State": {"lat": 29.8826, "lon": -97.9406, "roof": "outdoor"},  # UFCU Stadium, San Marcos, TX
    "Troy": {"lat": 31.8088, "lon": -85.97, "roof": "outdoor"},  # Veterans Memorial Stadium (AL), Troy, AL
    "Akron": {"lat": 41.0831, "lon": -81.5185, "roof": "outdoor"},  # InfoCision Stadium, Akron, OH
    "Ball State": {"lat": 40.1937, "lon": -85.3865, "roof": "outdoor"},  # Scheumann Stadium, Muncie, IN
    "Bowling Green": {"lat": 41.3748, "lon": -83.6513, "roof": "outdoor"},  # Doyt L. Perry Stadium, Bowling Green, OH
    "Buffalo": {"lat": 42.8867, "lon": -78.8784, "roof": "outdoor"},  # Broadview Stadium, Buffalo, NY
    "Central Michigan": {"lat": 43.5976, "lon": -84.7668, "roof": "outdoor"},  # Kelly/Shorts Stadium, Mount Pleasant, MI
    "Eastern Michigan": {"lat": 42.2411, "lon": -83.6118, "roof": "outdoor"},  # Rynearson Stadium, Ypsilanti, MI
    "Kent State": {"lat": 41.1513, "lon": -81.3578, "roof": "outdoor"},  # Zoeller Field at Dix Stadium, Kent, OH
    "Miami OH": {"lat": 39.5103, "lon": -84.7421, "roof": "outdoor"},  # Yager Stadium, Oxford, OH
    "Northern Illinois": {"lat": 41.9299, "lon": -88.7502, "roof": "outdoor"},  # Huskie Stadium, Dekalb, IL
    "Ohio": {"lat": 39.3289, "lon": -82.1012, "roof": "outdoor"},  # Peden Stadium, Athens, OH
    "Toledo": {"lat": 41.6529, "lon": -83.5378, "roof": "outdoor"},  # Glass Bowl, Toledo, OH
    "Western Michigan": {"lat": 42.2917, "lon": -85.5872, "roof": "outdoor"},  # Waldo Stadium, Kalamazoo, MI
    "Notre Dame": {"lat": 41.6992, "lon": -86.2374, "roof": "outdoor"},  # Notre Dame Stadium, Notre Dame, IN
    "Liberty": {"lat": 37.4138, "lon": -79.1422, "roof": "outdoor"},  # Williams Stadium (VA), Lynchburg, VA
    "UConn": {"lat": 41.7679, "lon": -72.6445, "roof": "outdoor"},  # Pratt & Whitney Stadium, East Hartford, CT
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
