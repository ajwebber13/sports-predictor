"""
situational.py
===============
Calculates situational adjustments to expected scoring.

Adjustments applied:
  1. Weather  — wind, temperature, precipitation (outdoor games only)
  2. Rest     — bye week boost, short week penalty
  3. Travel   — fatigue from long-distance travel
  4. Surface  — turf vs grass scoring differential

All adjustments return a points modifier (+/-) applied
to the team's expected score before simulation.

Sources:
  Weather factors based on published NFL/CFB weather research:
    - Ben Blatt (Harvard Sports Analysis) wind study
    - Warren Sharp weather analysis
    - Historical scoring data by conditions
"""

import math
from typing import Optional
from enhanced_data import GameContext


# ─────────────────────────────────────────────────────────────
# TEAM CITY COORDINATES
# Used for travel distance calculations.
# (lat, lon) for each FBS program's home city.
# ─────────────────────────────────────────────────────────────

TEAM_COORDINATES = {
    # SEC
    "Alabama":           (33.209, -87.550),
    "Arkansas":          (36.068, -94.174),
    "Auburn":            (32.602, -85.490),
    "Florida":           (29.650, -82.348),
    "Georgia":           (33.950, -83.374),
    "Kentucky":          (38.030, -84.495),
    "LSU":               (30.412, -91.183),
    "Mississippi State": (33.458, -88.789),
    "Missouri":          (38.934, -92.333),
    "Ole Miss":          (34.365, -89.528),
    "South Carolina":    (33.999, -81.031),
    "Tennessee":         (35.955, -83.925),
    "Texas A&M":         (30.615, -96.340),
    "Vanderbilt":        (36.144, -86.803),
    # Big Ten
    "Illinois":          (40.102, -88.227),
    "Indiana":           (39.184, -86.526),
    "Iowa":              (41.658, -91.554),
    "Maryland":          (38.990, -76.945),
    "Michigan":          (42.265, -83.749),
    "Michigan State":    (42.722, -84.481),
    "Minnesota":         (44.974, -93.231),
    "Nebraska":          (40.820, -96.706),
    "Northwestern":      (42.060, -87.670),
    "Ohio State":        (40.001, -83.020),
    "Penn State":        (40.798, -77.860),
    "Purdue":            (40.425, -86.922),
    "Rutgers":           (40.524, -74.436),
    "UCLA":              (34.161, -118.168),
    "USC":               (34.019, -118.288),
    "Washington":        (47.651, -122.303),
    "Wisconsin":         (43.070, -89.412),
    # Big 12
    "Arizona":           (32.229, -110.948),
    "Arizona State":     (33.426, -111.933),
    "Baylor":            (31.558, -97.117),
    "BYU":               (40.253, -111.649),
    "Cincinnati":        (39.130, -84.516),
    "Colorado":          (40.008, -105.267),
    "Houston":           (29.720, -95.413),
    "Iowa State":        (42.014, -93.636),
    "Kansas":            (38.954, -95.252),
    "Kansas State":      (39.198, -96.596),
    "Oklahoma":          (35.205, -97.443),
    "Oklahoma State":    (36.125, -97.068),
    "TCU":               (32.710, -97.368),
    "Texas":             (30.283, -97.732),
    "Texas Tech":        (33.590, -101.875),
    "UCF":               (28.601, -81.198),
    "Utah":              (40.760, -111.849),
    "West Virginia":     (39.650, -79.954),
    # ACC
    "Boston College":    (42.335, -71.168),
    "Clemson":           (34.683, -82.842),
    "Duke":              (36.001, -78.939),
    "Florida State":     (30.438, -84.298),
    "Georgia Tech":      (33.772, -84.393),
    "Louisville":        (38.213, -85.762),
    "Miami":             (25.814, -80.187),
    "NC State":          (35.770, -78.674),
    "North Carolina":    (35.905, -79.047),
    "Pittsburgh":        (40.441, -79.959),
    "Stanford":          (37.434, -122.161),
    "Syracuse":          (43.036, -76.136),
    "Virginia":          (38.031, -78.509),
    "Virginia Tech":     (37.220, -80.418),
    "Wake Forest":       (36.134, -80.277),
    # Pac-12 remnants / Independents
    "California":        (37.872, -122.259),
    "Notre Dame":        (41.698, -86.234),
    "Army":              (41.390, -73.952),
    "Navy":              (38.983, -76.481),
    # AAC
    "Memphis":           (35.149, -90.052),
    "SMU":               (32.843, -96.784),
    "Tulane":            (29.950, -90.118),
    "Tulsa":             (36.151, -95.967),
    "UTSA":              (29.576, -98.620),
    # Sun Belt
    "App State":         (36.213, -81.686),
    "Arkansas State":    (35.844, -90.699),
    "Georgia Southern":  (32.408, -81.777),
    "James Madison":     (38.434, -78.873),
    "Louisiana":         (30.213, -92.019),
    "Marshall":          (38.421, -82.438),
    "Old Dominion":      (36.886, -76.306),
    "South Alabama":     (30.697, -88.042),
    "Texas State":       (29.889, -97.940),
    "Troy":              (31.809, -85.978),
    # MWC
    "Air Force":         (38.997, -104.861),
    "Boise State":       (43.602, -116.199),
    "Colorado State":    (40.576, -105.083),
    "Fresno State":      (36.810, -119.747),
    "Hawai'i":           (21.298, -157.817),
    "Nevada":            (39.547, -119.815),
    "New Mexico":        (35.213, -106.622),
    "San Diego State":   (32.780, -117.073),
    "UNLV":              (36.105, -115.142),
    "Utah State":        (41.747, -111.810),
    "Wyoming":           (41.315, -105.566),
    # CUSA
    "Florida Atlantic":  (26.372, -80.099),
    "Liberty":           (37.354, -79.170),
    "Louisiana Tech":    (32.527, -92.640),
    "Middle Tennessee":  (35.846, -86.358),
    "New Mexico State":  (32.280, -106.750),
    "North Texas":       (33.209, -97.148),
    "Sam Houston":       (30.713, -95.548),
    "UTEP":              (31.768, -106.502),
    "Western Kentucky":  (36.968, -86.474),
}


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great circle distance between two points in miles."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def calc_travel_miles(team_name: str, opponent_city: Optional[tuple]) -> float:
    """Calculate travel miles for a team to an opponent's location."""
    home = TEAM_COORDINATES.get(team_name)
    if not home or not opponent_city:
        return 0.0
    return haversine_miles(home[0], home[1], opponent_city[0], opponent_city[1])


# ─────────────────────────────────────────────────────────────
# WEATHER ADJUSTMENTS
# ─────────────────────────────────────────────────────────────

def weather_scoring_adjustment(context: GameContext) -> float:
    """
    Returns a pts modifier applied to BOTH teams' expected scores.
    Negative = scoring suppressed, positive = scoring boosted.

    Based on:
    - Wind: Ben Blatt's research: ~1 pt total scoring reduction per 5mph above 15mph
    - Cold: ~0.5 pt scoring reduction per 10 degrees below 40°F
    - Rain: ~3 pt total reduction
    - Snow: ~5 pt total reduction
    - Dome: 0 adjustment
    """
    if context.is_dome:
        return 0.0

    adj = 0.0

    # Wind penalty (kicks in above 15 mph)
    if context.wind_mph and context.wind_mph > 15:
        excess_wind = context.wind_mph - 15
        adj -= (excess_wind / 5.0) * 0.5   # -0.5 pts per 5mph above 15

    # Temperature penalty (kicks in below 40°F)
    if context.temp_f is not None and context.temp_f < 40:
        cold_degrees = 40 - context.temp_f
        adj -= (cold_degrees / 10.0) * 0.4  # -0.4 pts per 10 degrees below 40

    # Precipitation
    if context.weather_cond:
        cond = context.weather_cond.lower()
        if "snow" in cond:
            adj -= 2.5
        elif "rain" in cond or "storm" in cond or "shower" in cond:
            adj -= 1.5
        elif "fog" in cond:
            adj -= 0.5

    # Turf vs grass (turf plays slightly faster, more scoring)
    if context.surface and "turf" in context.surface.lower():
        adj += 0.5

    return round(adj, 2)


def weather_team_split(context: GameContext) -> tuple:
    """
    Returns (home_adj, away_adj) — weather affects passing teams more.
    Away teams generally handle bad weather slightly worse.
    """
    base = weather_scoring_adjustment(context)
    if base == 0.0:
        return 0.0, 0.0
    # Away team takes slightly more of the weather penalty
    home_adj = base * 0.45
    away_adj = base * 0.55
    return round(home_adj, 2), round(away_adj, 2)


# ─────────────────────────────────────────────────────────────
# REST ADJUSTMENTS
# ─────────────────────────────────────────────────────────────

def rest_adjustment(rest_days: int) -> float:
    """
    Points adjustment based on days of rest.
    7 days = normal week, no adjustment.

    Bye week advantage: teams are well-rested, healthy, better-prepared.
    Short week: fatigue, limited prep time.

    Research: bye week teams win ~57% straight up, cover ~54% ATS.
    """
    if rest_days >= 14:
        return +2.5    # bye week
    if rest_days >= 12:
        return +1.5    # extra rest
    if rest_days >= 8:
        return +0.5    # slightly extra rest
    if rest_days == 7:
        return 0.0     # normal week
    if rest_days == 6:
        return -1.0    # short week
    if rest_days == 5:
        return -2.0    # very short week
    return -3.0        # under 5 days (rare)


def rest_advantage(home_rest: int, away_rest: int) -> tuple:
    """Returns (home_pts_adj, away_pts_adj) from rest differential."""
    return rest_adjustment(home_rest), rest_adjustment(away_rest)


# ─────────────────────────────────────────────────────────────
# TRAVEL ADJUSTMENTS
# ─────────────────────────────────────────────────────────────

def travel_adjustment(miles: float, is_home: bool = False) -> float:
    """
    Points adjustment for travel fatigue.
    Home team rarely travels so their adjustment is near zero.
    """
    if is_home or miles < 100:
        return 0.0
    if miles < 500:
        return -0.3
    if miles < 1000:
        return -0.7
    if miles < 1500:
        return -1.2
    if miles < 2500:
        return -1.8   # cross-country (e.g., East Coast to West Coast)
    return -2.5        # Hawaii trips, extreme distance


# ─────────────────────────────────────────────────────────────
# MARKET SIGNAL ADJUSTMENT
# ─────────────────────────────────────────────────────────────

def line_movement_signal(context: GameContext) -> tuple:
    """
    Returns (home_prob_adj, away_prob_adj) based on line movement.
    Sharp money moving a line is a signal — fade the public, follow the sharp.

    Positive line movement = line moved toward home team (sharp on home).
    Logic: if sharp money moved the line 2+ pts, add slight probability boost
    to the team getting the sharp action.
    """
    if context.line_movement is None or abs(context.line_movement) < 0.5:
        return 0.0, 0.0

    movement = context.line_movement
    if abs(movement) >= 3.0:
        boost = 3.0
    elif abs(movement) >= 1.5:
        boost = 1.5
    else:
        boost = 0.5

    if movement > 0:
        return +boost, -boost   # sharp money on home
    else:
        return -boost, +boost   # sharp money on away


# ─────────────────────────────────────────────────────────────
# COMBINED CONTEXT SUMMARY
# ─────────────────────────────────────────────────────────────

def apply_context_adjustments(
    expected_home: float,
    expected_away: float,
    context: GameContext,
) -> tuple:
    """
    Apply all situational adjustments to expected scores.
    Returns (adjusted_home_pts, adjusted_away_pts).
    """
    # Weather
    home_weather, away_weather = weather_team_split(context)

    # Rest
    home_rest, away_rest = rest_advantage(context.home_rest_days, context.away_rest_days)

    # Travel (home team rarely travels, away team does)
    away_travel = travel_adjustment(context.away_travel_miles, is_home=False)
    home_travel = travel_adjustment(context.home_travel_miles, is_home=True)

    # Apply all
    adj_home = expected_home + home_weather + home_rest + home_travel
    adj_away = expected_away + away_weather + away_rest + away_travel

    # Floor at 3 pts
    return max(adj_home, 3.0), max(adj_away, 3.0)


def summarize_context(context: GameContext, home: str, away: str) -> str:
    """Print-friendly context summary for display."""
    lines = []

    # Rest
    if context.home_on_bye:
        lines.append(f"  {home}: BYE WEEK (+2.5 pts)")
    elif context.home_rest_days < 7:
        lines.append(f"  {home}: SHORT WEEK {context.home_rest_days}d ({rest_adjustment(context.home_rest_days):+.1f} pts)")

    if context.away_on_bye:
        lines.append(f"  {away}: BYE WEEK (+2.5 pts)")
    elif context.away_rest_days < 7:
        lines.append(f"  {away}: SHORT WEEK {context.away_rest_days}d ({rest_adjustment(context.away_rest_days):+.1f} pts)")

    # Travel
    if context.away_travel_miles > 500:
        lines.append(f"  {away}: {context.away_travel_miles:.0f} miles traveled ({travel_adjustment(context.away_travel_miles):+.1f} pts)")

    # Weather
    weather = weather_scoring_adjustment(context)
    if not context.is_dome and weather != 0.0:
        lines.append(f"  Weather: {context.weather_summary()} ({weather:+.1f} pts/team)")
    elif context.is_dome:
        lines.append(f"  Venue: DOME")

    # Market
    lines.append(f"  Market: {context.market_signal()}")

    return "\n".join(lines) if lines else "  No significant situational factors"
