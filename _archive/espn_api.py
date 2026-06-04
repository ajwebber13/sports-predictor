"""
espn_api.py
============
ESPN public API client.
Pulls schedules, team stats, and betting odds for NFL + CFB.

No API key required. Works from any regular machine.

Endpoints used:
  Scoreboard : site.api.espn.com/apis/site/v2/sports/football/{league}/scoreboard
  Team stats : sports.core.api.espn.com/v2/sports/football/leagues/{league}/seasons/{year}/types/{type}/teams/{id}/statistics
  Teams list : site.api.espn.com/apis/site/v2/sports/football/{league}/teams
"""

import urllib.request
import json
import time
from typing import Optional
from predictor import TeamStats, MatchupInput, NFL_CONSTANTS, CFB_CONSTANTS

# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

BASE_SITE = "https://site.api.espn.com/apis/site/v2/sports/football"
BASE_CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues"

ESPN_NFL = "nfl"
ESPN_CFB = "college-football"

SEASON_TYPE_PRESEASON  = 1
SEASON_TYPE_REGULAR    = 2
SEASON_TYPE_POSTSEASON = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Origin": "https://www.espn.com",
    "Referer": "https://www.espn.com/",
}

# NFL team abbreviation → ESPN team ID
# Used to look up stats by team name/abbr
NFL_TEAM_IDS = {
    "ARI": 22, "ATL": 1,  "BAL": 33, "BUF": 2,  "CAR": 29,
    "CHI": 3,  "CIN": 4,  "CLE": 5,  "DAL": 6,  "DEN": 7,
    "DET": 8,  "GB":  9,  "HOU": 34, "IND": 11, "JAX": 30,
    "KC":  12, "LAC": 24, "LAR": 14, "LV":  13, "MIA": 15,
    "MIN": 16, "NE":  17, "NO":  18, "NYG": 19, "NYJ": 20,
    "PHI": 21, "PIT": 23, "SEA": 26, "SF":  25, "TB":  27,
    "TEN": 10, "WSH": 28,
}

# Default odds when ESPN doesn't have them
DEFAULT_SPREAD     = 0.0
DEFAULT_TOTAL      = 44.0
DEFAULT_ODDS_FAV   = -110
DEFAULT_ODDS_DOG   = -110


# ─────────────────────────────────────────────────────────────
# HTTP UTILITIES
# ─────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 2) -> dict:
    """GET request with retry logic. Returns empty dict on failure."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}   # not found, no retry
            if attempt < retries:
                time.sleep(1.5)
        except Exception as e:
            if attempt < retries:
                time.sleep(1.5)
    return {}


def test_connection() -> bool:
    """Quick connectivity check. Run this first to confirm ESPN API is reachable."""
    print("Testing ESPN API connection...")
    data = fetch(f"{BASE_SITE}/{ESPN_NFL}/teams?limit=1")
    if data:
        print("  ✓ Connected to ESPN API")
        return True
    print("  ✗ Cannot reach ESPN API. Check your internet connection.")
    return False


# ─────────────────────────────────────────────────────────────
# STAT PARSING UTILITIES
# ─────────────────────────────────────────────────────────────

def flatten_stats(categories: list) -> dict:
    """
    Flatten ESPN's nested categories/stats array into a single lookup dict.
    Stores both raw name and category-prefixed name.

    e.g., passing.yardsPerGame and yardsPerGame (last one wins on conflict)
    """
    flat = {}
    for cat in categories:
        cat_name = cat.get("name", "")
        for stat in cat.get("stats", []):
            name = stat.get("name")
            val  = stat.get("value")
            if name is not None and val is not None:
                flat[name] = float(val)
                flat[f"{cat_name}.{name}"] = float(val)
    return flat


def get_stat(flat: dict, *keys, default: float = 0.0) -> float:
    """Try each key in order. Return first found value, or default."""
    for key in keys:
        if key in flat:
            return flat[key]
    return default


def calc_yards_per_play(flat: dict, league: str) -> float:
    """
    Derive yards per play from available stats.
    Priority: direct ypp stat → calculate from pass/rush yards and attempts.
    """
    # Direct stat (best case)
    ypp = get_stat(flat, "yardsPerPlay", "offensiveYardsPerPlay", "avgYardsPerPlay", default=-1)
    if ypp > 0:
        return ypp

    # Calculate from passing + rushing yards per game
    pass_ypg = get_stat(flat, "passing.yardsPerGame", "passingYardsPerGame", default=0)
    rush_ypg = get_stat(flat, "rushing.yardsPerGame", "rushingYardsPerGame", default=0)
    total_ypg = pass_ypg + rush_ypg

    if total_ypg > 0:
        # NFL avg ~65 plays/game, CFB avg ~72 plays/game
        avg_plays = 65 if league == "NFL" else 72
        return round(total_ypg / avg_plays, 2)

    return NFL_CONSTANTS["league_avg_ypp"] if league == "NFL" else CFB_CONSTANTS["league_avg_ypp"]


def calc_def_yards_per_play(flat: dict, league: str) -> float:
    """Derive defensive yards per play allowed."""
    ypp = get_stat(flat,
        "defensiveYardsPerPlay", "opponentYardsPerPlay",
        "avgYardsAllowedPerPlay", "defensive.yardsPerPlay",
        default=-1)
    if ypp > 0:
        return ypp

    # Calculate from opponent yards per game allowed
    opp_ypg = get_stat(flat,
        "defensive.yardsAllowedPerGame", "yardsAllowedPerGame",
        "opponentYardsPerGame", default=0)

    if opp_ypg > 0:
        avg_plays = 65 if league == "NFL" else 72
        return round(opp_ypg / avg_plays, 2)

    return NFL_CONSTANTS["league_avg_ypp"] if league == "NFL" else CFB_CONSTANTS["league_avg_ypp"]


# ─────────────────────────────────────────────────────────────
# SCHEDULE (SCOREBOARD)
# ─────────────────────────────────────────────────────────────

def get_schedule(league: str, week: int, year: int, season_type: int = 2) -> list:
    """
    Pull schedule for a specific week.
    Returns list of game dicts with team info and odds.

    league: "nfl" or "college-football"
    season_type: 2=regular, 3=postseason, 1=preseason
    """
    espn_league = ESPN_NFL if league == "NFL" else ESPN_CFB
    params = f"seasontype={season_type}&week={week}&dates={year}"

    # CFB: add groups=80 to filter to FBS only
    if league == "CFB":
        params += "&groups=80"

    url = f"{BASE_SITE}/{espn_league}/scoreboard?{params}"
    data = fetch(url)

    if not data:
        print(f"  ✗ No schedule data for {league} Week {week} {year}")
        return []

    events = data.get("events", [])
    games  = []

    for event in events:
        comp = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])

        if len(competitors) < 2:
            continue

        # Identify home/away
        home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        # Extract odds
        odds_data = comp.get("odds", [{}])[0] if comp.get("odds") else {}
        home_ml   = odds_data.get("homeTeamOdds", {}).get("moneyLine", DEFAULT_ODDS_FAV)
        away_ml   = odds_data.get("awayTeamOdds", {}).get("moneyLine", DEFAULT_ODDS_DOG)
        spread    = odds_data.get("spread", DEFAULT_SPREAD)         # positive = home favored
        total     = odds_data.get("overUnder", DEFAULT_TOTAL)
        # Sometimes spread is in "details" string like "-3.5"
        if not spread and odds_data.get("details"):
            try:
                spread = abs(float(odds_data["details"]))
            except:
                spread = DEFAULT_SPREAD

        # If home team is the underdog, negate spread
        home_fav = odds_data.get("homeTeamOdds", {}).get("favorite", True)
        spread_line = spread if home_fav else -spread

        games.append({
            "event_id":        event.get("id"),
            "name":            event.get("name", "Unknown"),
            "date":            event.get("date", ""),
            "home": {
                "id":   home.get("team", {}).get("id"),
                "name": home.get("team", {}).get("displayName", "Home Team"),
                "abbr": home.get("team", {}).get("abbreviation", "HM"),
            },
            "away": {
                "id":   away.get("team", {}).get("id"),
                "name": away.get("team", {}).get("displayName", "Away Team"),
                "abbr": away.get("team", {}).get("abbreviation", "AW"),
            },
            "spread_line":  spread_line,   # positive = home favored
            "over_under":   total,
            "home_ml":      int(home_ml) if home_ml else DEFAULT_ODDS_FAV,
            "away_ml":      int(away_ml) if away_ml else DEFAULT_ODDS_DOG,
            "odds_source":  odds_data.get("provider", {}).get("name", "Unknown"),
            "has_odds":     bool(odds_data),
        })

    return games


def get_current_week(league: str, year: int) -> tuple[int, int]:
    """
    Return (week_number, season_type) for the current/next upcoming week.
    Falls back to week 1 regular season if offseason.
    """
    espn_league = ESPN_NFL if league == "NFL" else ESPN_CFB
    url = f"{BASE_SITE}/{espn_league}/scoreboard"
    data = fetch(url)
    if data:
        week   = data.get("week", {}).get("number", 1)
        s_type = data.get("season", {}).get("type", 2)
        return week, s_type
    return 1, 2


# ─────────────────────────────────────────────────────────────
# TEAM STATISTICS
# ─────────────────────────────────────────────────────────────

def get_team_stats_raw(league: str, team_id: str, year: int, season_type: int = 2) -> dict:
    """Fetch and return flattened stat dict for a team."""
    espn_league = ESPN_NFL if league == "NFL" else ESPN_CFB
    url = (f"{BASE_CORE}/{espn_league}/seasons/{year}"
           f"/types/{season_type}/teams/{team_id}/statistics")
    data = fetch(url)
    if not data:
        return {}
    categories = data.get("splits", {}).get("categories", [])
    return flatten_stats(categories)


def build_team_stats(
    league:      str,
    team_id:     str,
    team_name:   str,
    stats_year:  int,
    season_type: int = 2,
) -> TeamStats:
    """
    Build a TeamStats object from ESPN data.
    Uses stats_year season as the baseline (e.g., 2025 for upcoming 2026 season).

    Falls back to league average for any missing stats.
    """
    flat = get_team_stats_raw(league, team_id, stats_year, season_type)
    c = NFL_CONSTANTS if league == "NFL" else CFB_CONSTANTS

    if not flat:
        print(f"  ⚠  No stats found for {team_name} (ID:{team_id}). Using league averages.")
        return _default_team_stats(team_name, league)

    # Games played (for per-game calculations)
    games = get_stat(flat, "gamesPlayed", "general.gamesPlayed", default=17 if league == "NFL" else 12)

    # ── Offense ──────────────────────────────────────────────
    pts_off = get_stat(flat,
        "avgPoints", "pointsPerGame", "general.avgPoints",
        "scoring.pointsPerGame", "scoring.avgPoints",
        default=c["league_avg_pts"])

    ypp_off = calc_yards_per_play(flat, league)

    # ── Defense ──────────────────────────────────────────────
    pts_def = get_stat(flat,
        "avgPointsAllowed", "pointsAllowedPerGame",
        "defensive.avgPointsAllowed", "opponentPointsPerGame",
        "general.avgPointsAllowed",
        default=c["league_avg_pts"])

    # If pts_def wasn't found, try total points allowed / games
    if pts_def == c["league_avg_pts"]:
        pts_allowed_total = get_stat(flat,
            "pointsAllowed", "defensive.pointsAllowed",
            "totalPointsAllowed", default=0)
        if pts_allowed_total > 0:
            pts_def = pts_allowed_total / games

    ypp_def = calc_def_yards_per_play(flat, league)

    # ── Turnovers ─────────────────────────────────────────────
    to_given = get_stat(flat,
        "turnoversLost", "turnovers.turnoversLost",
        "totalTurnovers", "turnovers",
        default=c["league_avg_to_given"] * games) / games

    to_forced = get_stat(flat,
        "turnoversForced", "turnovers.turnoversForced",
        "takeaways",
        default=c["league_avg_to_forced"] * games) / games

    # ── Situational (estimates if splits unavailable) ─────────
    home_pts = pts_off * 1.06   # ~6% home scoring boost
    away_pts = pts_off * 0.94

    # ── Recent form (same as season avg — update manually or via last N games) ──
    recent_scored  = pts_off
    recent_allowed = pts_def

    return TeamStats(
        name               = team_name,
        league             = league,
        pts_per_game_off   = round(pts_off,    1),
        yards_per_play_off = round(ypp_off,    2),
        pts_per_game_def   = round(pts_def,    1),
        yards_per_play_def = round(ypp_def,    2),
        turnovers_given    = round(to_given,   2),
        turnovers_forced   = round(to_forced,  2),
        home_pts_avg       = round(home_pts,   1),
        away_pts_avg       = round(away_pts,   1),
        recent_pts_scored  = round(recent_scored,  1),
        recent_pts_allowed = round(recent_allowed, 1),
        sos                = 0.50,   # neutral default — adjust manually
        injury_adj         = 0.0,
    )


def _default_team_stats(name: str, league: str) -> TeamStats:
    """Fallback: league-average team when ESPN data is unavailable."""
    c = NFL_CONSTANTS if league == "NFL" else CFB_CONSTANTS
    return TeamStats(
        name=name, league=league,
        pts_per_game_off=c["league_avg_pts"],
        yards_per_play_off=c["league_avg_ypp"],
        pts_per_game_def=c["league_avg_pts"],
        yards_per_play_def=c["league_avg_ypp"],
        turnovers_given=c["league_avg_to_given"],
        turnovers_forced=c["league_avg_to_forced"],
        home_pts_avg=c["league_avg_pts"] * 1.05,
        away_pts_avg=c["league_avg_pts"] * 0.95,
        recent_pts_scored=c["league_avg_pts"],
        recent_pts_allowed=c["league_avg_pts"],
        sos=0.50, injury_adj=0.0,
    )


# ─────────────────────────────────────────────────────────────
# FULL PIPELINE: SCHEDULE + STATS → MATCHUP INPUTS
# ─────────────────────────────────────────────────────────────

def build_weekly_matchups(
    league:       str,
    week:         int,
    schedule_year: int,
    stats_year:   int,
    season_type:  int = 2,
    simulations:  int = 10000,
) -> list:
    """
    Full pipeline:
      1. Pull schedule for week
      2. For each game, pull both teams' stats
      3. Return list of (MatchupInput, game_meta) tuples

    schedule_year : year of the schedule (e.g., 2026 upcoming season)
    stats_year    : year of team stats (e.g., 2025 last season as baseline)
    """
    print(f"\n  Pulling {league} Week {week} schedule ({schedule_year})...")
    games = get_schedule(league, week, schedule_year, season_type)

    if not games:
        print(f"  No games found. The {schedule_year} schedule may not be posted yet for Week {week}.")
        return []

    print(f"  Found {len(games)} games. Pulling team stats from {stats_year} season...")

    matchups = []
    for i, game in enumerate(games, 1):
        print(f"  [{i}/{len(games)}] {game['name']}")

        home_stats = build_team_stats(
            league, game["home"]["id"], game["home"]["name"], stats_year, season_type
        )
        away_stats = build_team_stats(
            league, game["away"]["id"], game["away"]["name"], stats_year, season_type
        )
        time.sleep(0.3)  # be polite to ESPN's servers

        # Flag if odds weren't available
        if not game["has_odds"]:
            print(f"    ⚠  No odds available — using defaults (spread: PK, total: {DEFAULT_TOTAL})")

        matchup = MatchupInput(
            team_a          = home_stats,
            team_b          = away_stats,
            spread_line     = game["spread_line"],
            over_under_line = game["over_under"],
            team_a_odds     = game["home_ml"],
            team_b_odds     = game["away_ml"],
            neutral_site    = False,
            team_a_is_home  = True,
            simulations     = simulations,
        )
        matchups.append((matchup, game))

    return matchups


# ─────────────────────────────────────────────────────────────
# DIAGNOSTIC: PRINT RAW ESPN STATS FOR A TEAM
# ─────────────────────────────────────────────────────────────

def debug_team_stats(league: str, team_id: str, year: int, season_type: int = 2):
    """
    Print all stats ESPN returns for a team.
    Use this to see what's available and fine-tune your stat mappings.
    """
    espn_league = ESPN_NFL if league == "NFL" else ESPN_CFB
    url = (f"{BASE_CORE}/{espn_league}/seasons/{year}"
           f"/types/{season_type}/teams/{team_id}/statistics")
    data = fetch(url)
    if not data:
        print(f"No data for team {team_id}")
        return
    categories = data.get("splits", {}).get("categories", [])
    print(f"\nESPN Stats — Team ID: {team_id}  |  {league} {year}")
    print("=" * 50)
    for cat in categories:
        print(f"\n[{cat['name']}]")
        for s in cat.get("stats", []):
            print(f"  {s.get('name','?'):<35} {s.get('value','?')}")
