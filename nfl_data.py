"""
nfl_data.py
============
Pulls live NFL team stats from ESPN's public API.
No API key required.

Same pattern as cfb_data.py, with the offseason fallback logic
built in from day one (not bolted on after a live bug, like CFB was).
"""

import requests
from dataclasses import dataclass
from typing import Optional, Dict

ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports/football/nfl"

# ─────────────────────────────────────────────────────────────
# NFL TEAM ID MAP (ESPN IDs) — full "City Mascot" names, matching
# ESPN's displayName directly (unlike CFB, NFL only has 32 teams
# so there's no short-name collision risk requiring ID-matching)
# ─────────────────────────────────────────────────────────────

NFL_TEAM_IDS = {
    "Arizona Cardinals":     "22",
    "Atlanta Falcons":       "1",
    "Baltimore Ravens":      "33",
    "Buffalo Bills":         "2",
    "Carolina Panthers":     "29",
    "Chicago Bears":         "3",
    "Cincinnati Bengals":    "4",
    "Cleveland Browns":      "5",
    "Dallas Cowboys":        "6",
    "Denver Broncos":        "7",
    "Detroit Lions":         "8",
    "Green Bay Packers":     "9",
    "Houston Texans":        "34",
    "Indianapolis Colts":    "11",
    "Jacksonville Jaguars":  "30",
    "Kansas City Chiefs":    "12",
    "Las Vegas Raiders":     "13",
    "Los Angeles Chargers":  "24",
    "Los Angeles Rams":      "14",
    "Miami Dolphins":        "15",
    "Minnesota Vikings":     "16",
    "New England Patriots":  "17",
    "New Orleans Saints":    "18",
    "New York Giants":       "19",
    "New York Jets":         "20",
    "Philadelphia Eagles":   "21",
    "Pittsburgh Steelers":   "23",
    "San Francisco 49ers":   "25",
    "Seattle Seahawks":      "26",
    "Tampa Bay Buccaneers":  "27",
    "Tennessee Titans":      "10",
    "Washington Commanders": "28",
}

ID_TO_TEAM = {v: k for k, v in NFL_TEAM_IDS.items()}


# ─────────────────────────────────────────────────────────────
# DATA CLASS
# ─────────────────────────────────────────────────────────────

@dataclass
class NFLTeamStats:
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

    @property
    def net_yards_per_play(self) -> float:
        return round(self.yards_per_play_off - self.yards_per_play_def, 2)

    @property
    def win_pct(self) -> float:
        total = self.wins + self.losses
        return round(self.wins / total, 3) if total > 0 else 0.0

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


def _fetch_and_parse(team_name: str, team_id: str, season: int = None) -> Optional[NFLTeamStats]:
    """
    Fetch + parse team stats for a given season (or current if None).
    Returns None if ESPN gave us nothing usable (no stat categories).
    The team record endpoint doesn't reliably honor season= — same
    issue confirmed on the CFB side — so validity is gated on stat
    categories existing, not on win/loss record.
    """
    params = {"season": season} if season else None
    stats_data = _get(f"{ESPN_BASE}/teams/{team_id}/statistics", params=params)
    team_data  = _get(f"{ESPN_BASE}/teams/{team_id}", params=params)

    if not stats_data or not team_data:
        return None

    # Parse record (best-effort — may be empty regardless of season param)
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

    if not categories:
        return None

    games = wins + losses
    effective_games = games if games > 0 else 17  # NFL regular season length

    pts_off = all_stats.get("totalPointsPerGame",
              all_stats.get("points", 0) / effective_games)
    pts_def = all_stats.get("pointsAgainstPerGame",
              all_stats.get("pointsAgainst", 0) / effective_games)

    total_yards = all_stats.get("totalYards", all_stats.get("netYards", 0))
    total_plays = all_stats.get("totalPlays", all_stats.get("plays", 1))
    pass_yards  = all_stats.get("passingYards", all_stats.get("netPassingYards", 0))
    rush_yards  = all_stats.get("rushingYards", 0)

    ypp_off = round(total_yards / max(total_plays, 1), 2) if total_plays > 0 else 5.6
    pass_pg = round(pass_yards / effective_games, 1)
    rush_pg = round(rush_yards / effective_games, 1)

    fumbles    = all_stats.get("fumbles", 0)
    ints_given = all_stats.get("interceptions", 0)
    to_given   = round((fumbles + ints_given) / effective_games, 2)

    ints_taken = all_stats.get("defensiveInterceptions",
                 all_stats.get("interceptions_def", 0))
    fum_rec    = all_stats.get("fumblesRecovered", 0)
    to_forced  = round((ints_taken + fum_rec) / effective_games, 2)

    opp_yards = all_stats.get("yardsAllowed", all_stats.get("totalYardsAllowed", 0))
    opp_plays = all_stats.get("playsAllowed", total_plays)
    ypp_def   = round(opp_yards / max(opp_plays, 1), 2) if opp_plays > 0 else 5.6

    third_pct = all_stats.get("thirdDownConversionPct",
                all_stats.get("thirdDownEfficiency", 40.0))
    sacks_all = round(all_stats.get("sacksAllowed", all_stats.get("sacks", 0)) / effective_games, 2)
    sacks_for = round(all_stats.get("sacks", 0) / effective_games, 2)
    penalties = round(all_stats.get("penalties", 0) / effective_games, 1)

    # Sanity clamps — NFL scoring range is tighter than CFB
    if pts_off < 5 or pts_off > 45: pts_off = 23.0
    if pts_def < 5 or pts_def > 45: pts_def = 23.0
    if ypp_off < 2 or ypp_off > 8:  ypp_off = 5.6
    if ypp_def < 2 or ypp_def > 8:  ypp_def = 5.6

    return NFLTeamStats(
        team_name=team_name, team_id=team_id,
        wins=wins, losses=losses,
        home_wins=home_wins, home_losses=home_losses,
        away_wins=away_wins, away_losses=away_losses,
        pts_per_game=round(float(pts_off), 1),
        pts_allowed=round(float(pts_def), 1),
        yards_per_play_off=ypp_off, yards_per_play_def=ypp_def,
        pass_yards_pg=pass_pg, rush_yards_pg=rush_pg,
        turnovers_given=to_given, turnovers_forced=to_forced,
        third_down_pct=round(float(third_pct), 1),
        sacks_allowed=sacks_all, sacks_forced=sacks_for,
        penalties_pg=penalties,
    )


def _flat_defaults(team_name: str, team_id: str) -> NFLTeamStats:
    """Last-resort defaults when ESPN gives us nothing at all for a team."""
    return NFLTeamStats(
        team_name=team_name, team_id=team_id,
        wins=0, losses=0, home_wins=0, home_losses=0, away_wins=0, away_losses=0,
        pts_per_game=23.0, pts_allowed=23.0,
        yards_per_play_off=5.6, yards_per_play_def=5.6,
        pass_yards_pg=225.0, rush_yards_pg=115.0,
        turnovers_given=1.2, turnovers_forced=1.2,
        third_down_pct=40.0, sacks_allowed=2.5, sacks_forced=2.5, penalties_pg=6.0,
    )


def get_team_stats(team_name: str) -> Optional[NFLTeamStats]:
    """
    Fetch live NFL team stats from ESPN.

    If the current season has no real stats yet (preseason/offseason),
    automatically falls back to LAST season's real per-game numbers
    instead of flat defaults for every team. Record still correctly
    shows 0-0 for the current season either way.
    """
    team_id = NFL_TEAM_IDS.get(team_name)
    if not team_id:
        print(f"Unknown team: {team_name}")
        return None

    current = _fetch_and_parse(team_name, team_id)
    if current and (current.wins + current.losses) > 0:
        return current

    from datetime import datetime
    # NFL season runs Sep-Feb, so "last season" logic differs slightly
    # from CFB (Aug-Jan): treat Feb-July as offseason for last year's season
    now = datetime.now()
    last_year = now.year - 1 if now.month < 8 else now.year
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
    NFL weekly gaps: ~6 days is normal Sun-Sun, ~4 days is a short
    week (Thu game after a Sun game), ~13-14 days is a bye week.
    """
    from datetime import datetime, timezone
    team_id = NFL_TEAM_IDS.get(team_name)
    if not team_id:
        return 7

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


def get_nfl_events(days_ahead: int = 6) -> list:
    """
    Fetch upcoming NFL games in the next N days.
    NFL is Thu/Sun/Mon (mostly Sunday), so a 6-day window catches
    a full week's slate without pulling into the following week.
    """
    from datetime import datetime, timedelta

    today = datetime.now()
    dates = "-".join([
        today.strftime("%Y%m%d"),
        (today + timedelta(days=days_ahead)).strftime("%Y%m%d"),
    ])

    data = _get(f"{ESPN_BASE}/scoreboard", params={"dates": dates, "limit": 100})
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


if __name__ == "__main__":
    print("Testing NFL ESPN data pipeline...")
    stats = get_team_stats("Kansas City Chiefs")
    if stats:
        print(f"\n{stats.team_name}")
        print(f"Record: {stats.wins}-{stats.losses}")
        print(f"PPG: {stats.pts_per_game} | Pts Allowed: {stats.pts_allowed}")
        print(f"YPP Off: {stats.yards_per_play_off} | YPP Def: {stats.yards_per_play_def}")
        print(f"TO Margin: {stats.turnover_margin}")
    else:
        print("Could not fetch team stats — check ESPN API or team names in NFL_TEAM_IDS.")
