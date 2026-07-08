"""
cfb_data.py
============
Pulls live CFB team stats from ESPN's public API.
Covers all FBS teams (Power 4 + Group of 5).
No API key required.

Replaces static team_profiles.py with live data.
Updates automatically each week.
"""

import requests
from dataclasses import dataclass, field
from typing import Optional, Dict, List

ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports/football/college-football"

# ─────────────────────────────────────────────────────────────
# FBS TEAM ID MAP (ESPN IDs)
# ─────────────────────────────────────────────────────────────

FBS_TEAM_IDS = {
    # SEC
    "Alabama":           "333",
    "Arkansas":          "8",
    "Auburn":            "2",
    "Florida":           "57",
    "Georgia":           "61",
    "Kentucky":          "96",
    "LSU":               "99",
    "Mississippi State": "344",
    "Missouri":          "142",
    "Ole Miss":          "145",
    "South Carolina":    "2579",
    "Tennessee":         "2633",
    "Texas":             "251",
    "Texas A&M":         "245",
    "Vanderbilt":        "238",
    "Oklahoma":          "201",

    # Big Ten
    "Illinois":          "356",
    "Indiana":           "84",
    "Iowa":              "2294",
    "Maryland":          "120",
    "Michigan":          "130",
    "Michigan State":    "127",
    "Minnesota":         "135",
    "Nebraska":          "158",
    "Northwestern":      "77",
    "Ohio State":        "194",
    "Oregon":            "2483",
    "Penn State":        "213",
    "Purdue":            "2509",
    "Rutgers":           "164",
    "UCLA":              "26",
    "USC":               "30",
    "Washington":        "264",
    "Wisconsin":         "275",

    # ACC
    "Boston College":    "103",
    "California":        "25",
    "Clemson":           "228",
    "Duke":              "150",
    "Florida State":     "52",
    "Georgia Tech":      "59",
    "Louisville":        "97",
    "Miami":             "2390",
    "NC State":          "152",
    "North Carolina":    "153",
    "Pittsburgh":        "221",
    "SMU":               "2567",
    "Stanford":          "24",
    "Syracuse":          "183",
    "Virginia":          "258",
    "Virginia Tech":     "259",
    "Wake Forest":       "154",

    # Big 12
    "Arizona":           "12",
    "Arizona State":     "9",
    "Baylor":            "239",
    "BYU":               "252",
    "Cincinnati":        "2132",
    "Colorado":          "38",
    "Houston":           "248",
    "Iowa State":        "66",
    "Kansas":            "2305",
    "Kansas State":      "2306",
    "Oklahoma State":    "197",
    "TCU":               "2628",
    "Texas Tech":        "2641",
    "UCF":               "2116",
    "Utah":              "254",
    "West Virginia":     "277",

    # Group of 5 - AAC
    "Charlotte":         "2429",
    "East Carolina":     "151",
    "Florida Atlantic":  "2226",
    "Memphis":           "235",
    "Navy":              "2426",
    "North Texas":       "249",
    "Rice":              "242",
    "South Florida":     "58",
    "Temple":            "218",
    "Tulane":            "2655",
    "Tulsa":             "202",
    "UTSA":              "2636",
    "Wichita State":     "2724",

    # Mountain West
    "Air Force":         "2005",
    "Boise State":       "68",
    "Colorado State":    "36",
    "Fresno State":      "278",
    "Hawaii":            "62",
    "Nevada":            "2440",
    "New Mexico":        "167",
    "San Diego State":   "21",
    "San Jose State":    "23",
    "UNLV":              "2439",
    "Utah State":        "328",
    "Wyoming":           "2751",

    # Sun Belt
    "App State":         "2026",
    "Arkansas State":    "2032",
    "Coastal Carolina":  "324",
    "Georgia Southern":  "290",
    "Georgia State":     "2247",
    "James Madison":     "2253",
    "Louisiana":         "309",
    "Louisiana Monroe":  "2433",
    "Marshall":          "276",
    "Old Dominion":      "295",
    "South Alabama":     "6",
    "Southern Miss":     "2572",
    "Texas State":       "326",
    "Troy":              "2653",

    # MAC
    "Akron":             "2006",
    "Ball State":        "2050",
    "Bowling Green":     "189",
    "Buffalo":           "2084",
    "Central Michigan":  "2117",
    "Eastern Michigan":  "2199",
    "Kent State":        "2309",
    "Miami OH":          "193",
    "Northern Illinois": "2459",
    "Ohio":              "195",
    "Toledo":            "2649",
    "Western Michigan":  "2711",

    # Independents
    "Notre Dame":        "87",
    "Liberty":           "2335",
    "New Mexico State":  "2443",
    "UConn":             "41",
}

ID_TO_TEAM = {v: k for k, v in FBS_TEAM_IDS.items()}


# ─────────────────────────────────────────────────────────────
# DATA CLASS
# ─────────────────────────────────────────────────────────────

@dataclass
class CFBTeamStats:
    team_name:          str
    team_id:            str
    wins:               int
    losses:             int
    home_wins:          int
    home_losses:        int
    away_wins:          int
    away_losses:        int
    pts_per_game:       float
    pts_allowed:        float
    yards_per_play_off: float
    yards_per_play_def: float
    pass_yards_pg:      float
    rush_yards_pg:      float
    turnovers_given:    float
    turnovers_forced:   float
    third_down_pct:     float
    sacks_allowed:      float
    sacks_forced:       float
    penalties_pg:       float
    time_of_possession: float = 30.0

    @property
    def net_yards_per_play(self) -> float:
        return round(self.yards_per_play_off - self.yards_per_play_def, 2)

    @property
    def win_pct(self) -> float:
        total = self.wins + self.losses
        return round(self.wins / total, 3) if total > 0 else 0.0

    @property
    def home_win_pct(self) -> float:
        total = self.home_wins + self.home_losses
        return round(self.home_wins / total, 3) if total > 0 else 0.0

    @property
    def away_win_pct(self) -> float:
        total = self.away_wins + self.away_losses
        return round(self.away_wins / total, 3) if total > 0 else 0.0

    @property
    def turnover_margin(self) -> float:
        return round(self.turnovers_forced - self.turnovers_given, 1)


# ─────────────────────────────────────────────────────────────
# FETCHERS
# ─────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> dict:
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"ESPN API error {url}: {e}")
        return {}


def _fetch_and_parse(team_name: str, team_id: str, season: int = None):
    """
    Fetch + parse team stats for a given season (or current if None).
    Returns None if ESPN gave us nothing usable (no stat categories at
    all) for that team/season — that's the real "no data" signal.
    The team record endpoint (wins/losses) does NOT reliably honor the
    season param, so it is NOT used to decide whether data is valid —
    only whether the stats categories themselves came back.
    """
    params = {"season": season} if season else None
    stats_data = _get(f"{ESPN_BASE}/teams/{team_id}/statistics", params=params)
    team_data  = _get(f"{ESPN_BASE}/teams/{team_id}", params=params)

    if not stats_data or not team_data:
        return None

    # Parse record (best-effort — often empty regardless of season param)
    team_info = team_data.get("team", {})
    record_items = team_info.get("record", {}).get("items", [])

    wins = losses = home_wins = home_losses = away_wins = away_losses = 0
    for rec in record_items:
        rec_type = rec.get("type", "")
        stats = {s["name"]: s["value"] for s in rec.get("stats", [])}
        if rec_type == "total":
            wins   = int(stats.get("wins", 0))
            losses = int(stats.get("losses", 0))
        elif rec_type == "home":
            home_wins   = int(stats.get("wins", 0))
            home_losses = int(stats.get("losses", 0))
        elif rec_type == "road":
            away_wins   = int(stats.get("wins", 0))
            away_losses = int(stats.get("losses", 0))

    # Parse stats
    all_stats = {}
    categories = stats_data.get("results", {}).get("stats", {}).get("categories", [])
    for cat in categories:
        for stat in cat.get("stats", []):
            name = stat["name"]
            val  = stat.get("perGameValue", stat.get("value", 0.0))
            all_stats[name] = float(val)

    # No stat categories at all — genuinely nothing available for this
    # team/season. This is the real "no data" case (not a broken
    # record endpoint, which we no longer trust either way).
    if not categories:
        return None

    games = wins + losses
    # The record endpoint doesn't reliably return win/loss even when
    # real stats exist (confirmed: statistics endpoint honors season=,
    # team endpoint's record does not). If we have real stat categories
    # but no confirmed game count, assume a full season (13 games) for
    # the raw-total/games math below instead of dividing by a fake "1".
    effective_games = games if games > 0 else 13

    # Scoring
    pts_off = all_stats.get("totalPointsPerGame",
              all_stats.get("points", 0) / effective_games)
    pts_def = all_stats.get("pointsAgainstPerGame",
              all_stats.get("pointsAgainst", 0) / effective_games)

    # Yards per play (calculated from total yards / plays)
    total_yards   = all_stats.get("totalYards", all_stats.get("netYards", 0))
    total_plays   = all_stats.get("totalPlays", all_stats.get("plays", 1))
    pass_yards    = all_stats.get("passingYards", all_stats.get("netPassingYards", 0))
    rush_yards    = all_stats.get("rushingYards", 0)

    ypp_off = round(total_yards / max(total_plays, 1), 2) if total_plays > 0 else 5.5
    pass_pg = round(pass_yards / effective_games, 1)
    rush_pg = round(rush_yards / effective_games, 1)

    # Turnovers
    fumbles    = all_stats.get("fumbles", 0)
    ints_given = all_stats.get("interceptions", 0)
    to_given   = round((fumbles + ints_given) / effective_games, 2)

    ints_taken = all_stats.get("defensiveInterceptions",
                 all_stats.get("interceptions_def", 0))
    fum_rec    = all_stats.get("fumblesRecovered", 0)
    to_forced  = round((ints_taken + fum_rec) / effective_games, 2)

    # Defensive yards per play
    opp_yards  = all_stats.get("yardsAllowed", all_stats.get("totalYardsAllowed", 0))
    opp_plays  = all_stats.get("playsAllowed", total_plays)
    ypp_def    = round(opp_yards / max(opp_plays, 1), 2) if opp_plays > 0 else 5.5

    # Other
    third_pct  = all_stats.get("thirdDownConversionPct",
                 all_stats.get("thirdDownEfficiency", 40.0))
    sacks_all  = round(all_stats.get("sacksAllowed", all_stats.get("sacks", 0)) / effective_games, 2)
    sacks_for  = round(all_stats.get("sacks", 0) / effective_games, 2)
    penalties  = round(all_stats.get("penalties", 0) / effective_games, 1)

    # Sanity clamps if ESPN returns zeros or nonsense values
    if pts_off < 5 or pts_off > 70:   pts_off = 28.0
    if pts_def < 5 or pts_def > 70:   pts_def = 28.0
    if ypp_off < 2 or ypp_off > 10:   ypp_off = 5.5
    if ypp_def < 2 or ypp_def > 10:   ypp_def = 5.5

    return CFBTeamStats(
        team_name          = team_name,
        team_id            = team_id,
        wins               = wins,
        losses             = losses,
        home_wins          = home_wins,
        home_losses        = home_losses,
        away_wins          = away_wins,
        away_losses        = away_losses,
        pts_per_game       = round(float(pts_off), 1),
        pts_allowed        = round(float(pts_def), 1),
        yards_per_play_off = ypp_off,
        yards_per_play_def = ypp_def,
        pass_yards_pg      = pass_pg,
        rush_yards_pg      = rush_pg,
        turnovers_given    = to_given,
        turnovers_forced   = to_forced,
        third_down_pct     = round(float(third_pct), 1),
        sacks_allowed      = sacks_all,
        sacks_forced       = sacks_for,
        penalties_pg       = penalties,
    )


def _flat_defaults(team_name: str, team_id: str) -> "CFBTeamStats":
    """Last-resort defaults when ESPN gives us nothing at all for a team."""
    return CFBTeamStats(
        team_name=team_name, team_id=team_id,
        wins=0, losses=0, home_wins=0, home_losses=0, away_wins=0, away_losses=0,
        pts_per_game=28.0, pts_allowed=28.0,
        yards_per_play_off=5.5, yards_per_play_def=5.5,
        pass_yards_pg=220.0, rush_yards_pg=160.0,
        turnovers_given=1.5, turnovers_forced=1.5,
        third_down_pct=40.0, sacks_allowed=2.0, sacks_forced=2.0, penalties_pg=6.0,
    )


def get_team_stats(team_name: str):
    """
    Fetch live CFB team stats from ESPN.

    If the current season has no real stats yet (preseason/offseason —
    like right now), automatically falls back to LAST season's real
    per-game numbers instead of flat 28-28 defaults for every team.
    Record still correctly shows 0-0 for the current season either way.
    """
    team_id = FBS_TEAM_IDS.get(team_name)
    if not team_id:
        print(f"Unknown team: {team_name}")
        return None

    current = _fetch_and_parse(team_name, team_id)
    if current and (current.wins + current.losses) > 0:
        return current

    from datetime import datetime
    last_year = datetime.now().year - 1 if datetime.now().month < 8 else datetime.now().year
    prior = _fetch_and_parse(team_name, team_id, season=last_year)
    if prior is not None:
        prior.wins = prior.losses = 0
        prior.home_wins = prior.home_losses = 0
        prior.away_wins = prior.away_losses = 0
        return prior

    if current is not None:
        return current

    return _flat_defaults(team_name, team_id)



def get_rest_days(team_name: str) -> int:
    """
    Days since the team's last completed game.
    Football teams play weekly (6-8 day gaps normally), so this is
    used to detect BYE WEEKS (10+ days), not daily back-to-backs.
    """
    from datetime import datetime, timezone
    team_id = FBS_TEAM_IDS.get(team_name)
    if not team_id:
        return 7  # default: normal weekly gap

    data = _get(f"{ESPN_BASE}/teams/{team_id}/schedule")
    if not data:
        return 7

    now = datetime.now(timezone.utc)
    last_game_date = None

    for event in data.get("events", []):
        date_str = event.get("date", "")
        try:
            game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if game_date < now:
                if last_game_date is None or game_date > last_game_date:
                    last_game_date = game_date
        except Exception:
            continue

    if last_game_date is None:
        return 7

    return max((now - last_game_date).days, 0)


def get_cfb_events(days_ahead: int = 7) -> list:
    """
    Fetch upcoming FBS games in the next N days.
    Unlike WNBA (daily games -> just check "today"), CFB is
    mostly Saturday with some Tue/Wed MACtion, so this pulls a
    week-wide window instead of a single date.
    """
    from datetime import datetime, timedelta

    today  = datetime.now()
    dates  = "-".join([
        today.strftime("%Y%m%d"),
        (today + timedelta(days=days_ahead)).strftime("%Y%m%d"),
    ])

    data = _get(f"{ESPN_BASE}/scoreboard", params={"dates": dates, "groups": "80", "limit": 200})
    if not data:
        return []

    events = []
    for event in data.get("events", []):
        status_name = event.get("status", {}).get("type", {}).get("name", "")
        if status_name == "STATUS_FINAL":
            continue

        competitions = event.get("competitions", [{}])
        if not competitions:
            continue
        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_id = next((c["team"].get("id", "") for c in competitors if c.get("homeAway") == "home"), "")
        away_id = next((c["team"].get("id", "") for c in competitors if c.get("homeAway") == "away"), "")

        # Resolve to OUR short team names (e.g. "Georgia") via ESPN ID —
        # displayName ("Georgia Bulldogs") won't match FBS_TEAM_IDS keys
        home_team = ID_TO_TEAM.get(str(home_id))
        away_team = ID_TO_TEAM.get(str(away_id))
        game_time = event.get("date", "")

        if home_team and away_team:
            events.append({
                "home_team": home_team,
                "away_team": away_team,
                "game_time": game_time,
                "event_id":  event.get("id", ""),
            })

    return events


def get_all_fbs_stats() -> Dict[str, CFBTeamStats]:
    """Fetch stats for all FBS teams. Takes ~2 minutes."""
    results = {}
    total = len(FBS_TEAM_IDS)
    for i, team_name in enumerate(FBS_TEAM_IDS, 1):
        print(f"[{i}/{total}] Fetching {team_name}...")
        stats = get_team_stats(team_name)
        if stats:
            results[team_name] = stats
    print(f"\nDone. Fetched {len(results)}/{total} teams.")
    return results


def build_enhanced_profile(stats: CFBTeamStats):
    """
    Convert CFBTeamStats into EnhancedProfile for use with
    the existing EnhancedPredictionEngine.
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from enhanced_data import EnhancedProfile, AdvancedMetrics, MultiYearProfile, ATSRecord

    advanced = AdvancedMetrics(
        epa_off          = 0.0,   # ESPN doesn't have EPA — use CFBD for this
        epa_def          = 0.0,
        success_rate_off = min(stats.third_down_pct / 100 * 1.2, 0.65),
        success_rate_def = 0.42,
        pace             = 70.0,
        explosiveness    = 1.0,
        havoc            = min(stats.sacks_forced * 0.1 + 0.15, 0.30),
        elo              = 1500.0 + (stats.win_pct - 0.5) * 300,
        sp_rating        = 0.0,
    )

    history = MultiYearProfile(
        weighted_pts_off = stats.pts_per_game,
        weighted_pts_def = stats.pts_allowed,
        weighted_epa_off = 0.0,
        weighted_epa_def = 0.0,
        trend_off        = 0.0,
        trend_def        = 0.0,
        years_available  = 1,
    )

    ats_rec = ATSRecord(
        overall_w=0, overall_l=0, overall_p=0, overall_pct=0.5,
        home_w=0, home_l=0, home_pct=0.5,
        away_w=0, away_l=0, away_pct=0.5,
        ou_over_w=0, ou_under_w=0, ou_pct=0.5,
        games_rated=0,
    )

    return EnhancedProfile(
        team_name    = stats.team_name,
        league       = "CFB",
        pts_off      = stats.pts_per_game,
        pts_def      = stats.pts_allowed,
        ypp_off      = stats.yards_per_play_off,
        ypp_def      = stats.yards_per_play_def,
        to_given     = stats.turnovers_given,
        to_forced    = stats.turnovers_forced,
        home_pts_off = round(stats.pts_per_game * 1.05, 1),
        away_pts_off = round(stats.pts_per_game * 0.95, 1),
        recent_off   = stats.pts_per_game,
        recent_def   = stats.pts_allowed,
        sos          = 0.5 + (stats.win_pct - 0.5) * 0.2,
        injury_adj   = 0.0,
        advanced     = advanced,
        history      = history,
        ats          = ats_rec,
    )


# Cache for session
_stats_cache: Dict[str, CFBTeamStats] = {}


def get_profile(team_name: str):
    """
    Get EnhancedProfile for a team using live ESPN data.
    Caches results within session to avoid repeated API calls.
    """
    if team_name not in _stats_cache:
        stats = get_team_stats(team_name)
        if stats:
            _stats_cache[team_name] = stats

    stats = _stats_cache.get(team_name)
    if not stats:
        return None

    return build_enhanced_profile(stats)


if __name__ == "__main__":
    print("Testing CFB ESPN data pipeline...")
    stats = get_team_stats("Georgia")
    if stats:
        print(f"\n{stats.team_name}")
        print(f"Record: {stats.wins}-{stats.losses} ({stats.win_pct:.1%})")
        print(f"Home: {stats.home_wins}-{stats.home_losses} | Away: {stats.away_wins}-{stats.away_losses}")
        print(f"PPG: {stats.pts_per_game} | Pts Allowed: {stats.pts_allowed}")
        print(f"YPP Off: {stats.yards_per_play_off} | YPP Def: {stats.yards_per_play_def}")
        print(f"TO Margin: {stats.turnover_margin}")

    profile = get_profile("Georgia")
    if profile:
        print(f"\nEnhancedProfile built successfully for {profile.team_name}")
        print(f"Elo: {profile.advanced.elo:.0f}")