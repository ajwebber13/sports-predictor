"""
ncaab_data.py
==============
Pulls live College Basketball data from ESPN's public API.
No API key required.

Data available:
  - Team stats (pts, rebounds, assists, turnovers, pace)
  - Win/loss records, home/away splits
  - Full rosters with player details
  - Today's scoreboard / game schedule
"""

import requests
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime, timezone

BASE = "http://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"


# ─────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────

@dataclass
class NCAABTeamStats:
    team_name:          str
    team_id:            str
    wins:               int
    losses:             int
    home_wins:          int
    home_losses:        int
    away_wins:          int
    away_losses:        int
    pts_per_game:       float
    opp_pts_per_game:   float
    rebounds_per_game:  float
    assists_per_game:   float
    turnovers_per_game: float
    fg_pct:             float
    three_pct:          float
    pace:               float
    off_rating:         float
    def_rating:         float

    @property
    def net_rating(self) -> float:
        return round(self.off_rating - self.def_rating, 1)

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


@dataclass
class NCAABPlayer:
    player_id: str
    name:      str
    position:  str
    jersey:    str
    height:    str
    age:       int
    pts:       float = 0.0
    reb:       float = 0.0
    ast:       float = 0.0
    minutes:   float = 0.0
    status:    str   = "Active"


@dataclass
class NCAABRoster:
    team_name: str
    players:   List[NCAABPlayer] = field(default_factory=list)

    def starters(self) -> List[NCAABPlayer]:
        return sorted(self.players, key=lambda p: p.minutes, reverse=True)[:5]

    def key_players(self) -> List[NCAABPlayer]:
        return sorted(self.players, key=lambda p: p.pts, reverse=True)[:3]


# ─────────────────────────────────────────────────────────────
# HTTP HELPER
# ─────────────────────────────────────────────────────────────

def _get(url: str, params: dict = None) -> dict:
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"ESPN API error: {e}")
        return {}


# ─────────────────────────────────────────────────────────────
# TEAM LOOKUP — search by name since there are 350+ teams
# ─────────────────────────────────────────────────────────────

def find_team_id(team_name: str) -> Optional[str]:
    """Search ESPN for a team by name and return its ID."""
    data = _get(f"{BASE}/teams", params={"limit": 500})
    if not data:
        return None
    for team in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = team.get("team", {})
        if (t.get("displayName", "").lower() == team_name.lower() or
                t.get("shortDisplayName", "").lower() == team_name.lower() or
                t.get("name", "").lower() == team_name.lower()):
            return t.get("id")
    return None


def search_teams(query: str, limit: int = 10) -> List[dict]:
    """Search for teams matching a query string. Useful for finding exact ESPN names."""
    data = _get(f"{BASE}/teams", params={"limit": 500})
    if not data:
        return []
    results = []
    query_lower = query.lower()
    for team in data.get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", []):
        t = team.get("team", {})
        name = t.get("displayName", "")
        if query_lower in name.lower():
            results.append({"id": t.get("id"), "name": name})
        if len(results) >= limit:
            break
    return results


# ─────────────────────────────────────────────────────────────
# DATA FETCHERS
# ─────────────────────────────────────────────────────────────

def get_team_stats(team_name: str) -> Optional[NCAABTeamStats]:
    """Fetch live team stats from ESPN by team name."""
    team_id = find_team_id(team_name)
    if not team_id:
        print(f"Team not found: {team_name}")
        return None

    stats_data = _get(f"{BASE}/teams/{team_id}/statistics")
    team_data  = _get(f"{BASE}/teams/{team_id}")

    if not stats_data or not team_data:
        return None

    # Parse win/loss record
    team_info      = team_data.get("team", {})
    record_summary = team_info.get("record", {}).get("items", [])

    wins = losses = 0
    home_wins = home_losses = away_wins = away_losses = 0

    for rec in record_summary:
        rec_type = rec.get("type", "")
        stats    = {s["name"]: s["value"] for s in rec.get("stats", [])}
        if rec_type == "total":
            wins   = int(stats.get("wins", 0))
            losses = int(stats.get("losses", 0))
        elif rec_type == "home":
            home_wins   = int(stats.get("wins", 0))
            home_losses = int(stats.get("losses", 0))
        elif rec_type == "road":
            away_wins   = int(stats.get("wins", 0))
            away_losses = int(stats.get("losses", 0))

    # Parse team stats
    all_stats  = {}
    categories = stats_data.get("results", {}).get("stats", {}).get("categories", [])
    for cat in categories:
        for stat in cat.get("stats", []):
            all_stats[stat["name"]] = stat.get("value", 0.0)

    pts       = all_stats.get("avgPoints",        all_stats.get("points",        72.0))
    opp_pts   = all_stats.get("avgPointsAgainst", all_stats.get("pointsAgainst", 72.0))
    reb       = all_stats.get("avgRebounds",       35.0)
    ast       = all_stats.get("avgAssists",        14.0)
    to        = all_stats.get("avgTurnovers",      13.0)
    fg_pct    = all_stats.get("avgFieldGoalPct",   all_stats.get("fieldGoalPct",  0.44))
    three_pct = all_stats.get("avgThreePointPct",  all_stats.get("threePointPct", 0.33))
    off_rtg   = all_stats.get("offensiveRating",   round(float(pts) / 0.95, 1))
    def_rtg   = all_stats.get("defensiveRating",   round(float(opp_pts) / 0.95, 1))
    pace      = all_stats.get("pace",              68.0)

    return NCAABTeamStats(
        team_name          = team_name,
        team_id            = team_id,
        wins               = wins,
        losses             = losses,
        home_wins          = home_wins,
        home_losses        = home_losses,
        away_wins          = away_wins,
        away_losses        = away_losses,
        pts_per_game       = round(float(pts),       1),
        opp_pts_per_game   = round(float(opp_pts),   1),
        rebounds_per_game  = round(float(reb),        1),
        assists_per_game   = round(float(ast),        1),
        turnovers_per_game = round(float(to),         1),
        fg_pct             = round(float(fg_pct),     3),
        three_pct          = round(float(three_pct),  3),
        pace               = round(float(pace),       1),
        off_rating         = round(float(off_rtg),    1),
        def_rating         = round(float(def_rtg),    1),
    )


def get_roster(team_name: str) -> Optional[NCAABRoster]:
    """Fetch full roster from ESPN."""
    team_id = find_team_id(team_name)
    if not team_id:
        return None

    data = _get(f"{BASE}/teams/{team_id}/roster")
    if not data:
        return None

    players = []
    for athlete in data.get("athletes", []):
        pos_info = athlete.get("position", {})
        pos      = pos_info.get("abbreviation", "G") if isinstance(pos_info, dict) else "G"

        player = NCAABPlayer(
            player_id = athlete.get("id", ""),
            name      = athlete.get("displayName", "Unknown"),
            position  = pos,
            jersey    = athlete.get("jersey", "0"),
            height    = athlete.get("displayHeight", "N/A"),
            age       = athlete.get("age", 0),
            status    = athlete.get("status", {}).get("type", {}).get("name", "Active")
                        if isinstance(athlete.get("status"), dict) else "Active",
        )
        players.append(player)

    return NCAABRoster(team_name=team_name, players=players)


def get_rest_days(team_name: str) -> int:
    """Calculate days since last game."""
    team_id = find_team_id(team_name)
    if not team_id:
        return 2

    data = _get(f"{BASE}/teams/{team_id}/schedule")
    if not data:
        return 2

    now            = datetime.now(timezone.utc)
    last_game_date = None

    for event in data.get("events", []):
        date_str = event.get("date", "")
        try:
            game_date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if game_date < now:
                if last_game_date is None or game_date > last_game_date:
                    last_game_date = game_date
        except:
            continue

    if last_game_date:
        return max(1, (now - last_game_date).days)
    return 2


def get_ncaab_events() -> list:
    """Fetch today's college basketball games from ESPN."""
    data = _get(f"{BASE}/scoreboard")
    if not data:
        return []

    events = []
    for event in data.get("events", []):
        competitions = event.get("competitions", [{}])
        if not competitions:
            continue
        comp        = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), "")
        away_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), "")
        game_time = event.get("date", "")

        if home_team and away_team:
            events.append({
                "home_team": home_team,
                "away_team": away_team,
                "game_time": game_time,
                "event_id":  event.get("id", ""),
            })

    return events


# ─────────────────────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing ESPN NCAAB API...")

    print("\nSearching for Duke...")
    results = search_teams("Duke")
    for r in results:
        print(f"  {r['id']} — {r['name']}")

    print("\nFetching today's games...")
    events = get_ncaab_events()
    print(f"  {len(events)} games found")
    for e in events[:3]:
        print(f"  {e['away_team']} @ {e['home_team']} — {e['game_time']}")
