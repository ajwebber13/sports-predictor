"""
intel_feed.py — Culture & Pulse Analytics
Phase 3: Injury Feed + Line Movement Tracker

Pulls live injury reports and line movement data and injects
them into the prediction pipeline before alerts are generated.

Usage (standalone):
  python intel_feed.py nba        # show NBA injuries + line moves
  python intel_feed.py wnba       # show WNBA injuries + line moves

Auto-used by nba_wnba_predict.py when imported.

Sources:
  - Injuries: ESPN API (free, no key needed)
  - Line movement: The Odds API (free tier = 500 req/month)
    Get your free key at: https://the-odds-api.com
    Paste it below or set env var: "4715e62920e940cec7ec335194cf5e2a"
"""

import os
import requests
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Get a free key at https://the-odds-api.com (500 requests/month free)
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "4715e62920e940cec7ec335194cf5e2a")  

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

ESPN_INJURY_URLS = {
    "NBA":  "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries",
    "WNBA": "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/injuries",
}

ODDS_API_SPORT_KEYS = {
    "NBA":  "basketball_nba",
    "WNBA": "basketball_wnba",
}

# Impact weights by position (how much a player affects the line)
POSITION_IMPACT = {
    "PG":  0.9,   # Point guard — high impact
    "SG":  0.7,
    "SF":  0.7,
    "PF":  0.6,
    "C":   0.6,
    "G":   0.8,
    "F":   0.65,
    "":    0.5,   # Unknown position
}

# Status severity
INJURY_SEVERITY = {
    "Out":          1.0,
    "Doubtful":     0.75,
    "Questionable": 0.4,
    "Probable":     0.1,
    "Day-To-Day":   0.3,
}


# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

class InjuryReport:
    def __init__(self, team: str, player: str, position: str,
                 status: str, description: str):
        self.team        = team
        self.player      = player
        self.position    = position
        self.status      = status
        self.description = description
        self.impact      = self._calc_impact()

    def _calc_impact(self) -> float:
        pos_weight = POSITION_IMPACT.get(self.position.upper(), 0.5)
        sev_weight = INJURY_SEVERITY.get(self.status, 0.3)
        return round(pos_weight * sev_weight, 3)

    def __repr__(self):
        return f"{self.player} ({self.position}) — {self.status}: {self.description}"


class LineMovement:
    def __init__(self, team: str, opening_odds: int, current_odds: int):
        self.team          = team
        self.opening_odds  = opening_odds
        self.current_odds  = current_odds
        self.movement      = current_odds - opening_odds
        self.direction     = self._direction()
        self.sharp_signal  = self._sharp_signal()

    def _direction(self) -> str:
        if self.movement > 5:
            return "STEAMED UP ↑"     # Line moved in team's favor
        elif self.movement < -5:
            return "STEAMED DOWN ↓"   # Line moved against team
        return "FLAT →"

    def _sharp_signal(self) -> str:
        """
        If line moves toward a team despite public betting against them,
        that's sharp (professional) money. Simple heuristic here.
        """
        if abs(self.movement) >= 10:
            return "⚡ SHARP MOVE"
        elif abs(self.movement) >= 5:
            return "👀 WATCH"
        return ""

    def __repr__(self):
        return (f"{self.team}: {self.opening_odds:+d} → {self.current_odds:+d} "
                f"({self.direction}) {self.sharp_signal}")


# ─────────────────────────────────────────────
# INJURY FEED
# ─────────────────────────────────────────────

def fetch_injuries(league: str) -> dict[str, list[InjuryReport]]:
    """
    Returns dict of {team_name: [InjuryReport, ...]}
    Uses ESPN's free injury API.
    """
    url = ESPN_INJURY_URLS.get(league)
    if not url:
        return {}

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [Intel] Injury feed error: {e}")
        return {}

    injuries = {}
    for team_obj in data.get("injuries", []):
        team_name = team_obj.get("displayName", "Unknown")
        for item in team_obj.get("injuries", []):
            athlete   = item.get("athlete", {})
            player    = athlete.get("displayName", "Unknown")
            pos_info  = athlete.get("position", {})
            pos       = pos_info.get("abbreviation", "") if isinstance(pos_info, dict) else ""
            status    = item.get("status", "Unknown")
            desc      = item.get("shortComment", item.get("longComment", ""))

            report = InjuryReport(team_name, player, pos, status, desc)
            injuries.setdefault(team_name, []).append(report)

    return injuries


def get_team_injury_impact(team_name: str,
                            injuries: dict[str, list[InjuryReport]]) -> tuple[float, list]:
    """
    Returns (total_impact_score, injury_list) for a team.
    Impact score 0-1+: higher = more significant injuries.
    """
    team_injuries = injuries.get(team_name, [])
    if not team_injuries:
        return 0.0, []

    # Cap at 3 most impactful players
    sorted_injuries = sorted(team_injuries, key=lambda x: x.impact, reverse=True)[:3]
    total_impact    = sum(i.impact for i in sorted_injuries)

    return round(total_impact, 3), sorted_injuries


def injury_adj_pts(impact_score: float) -> float:
    """
    Convert impact score to point adjustment.
    Max ~4 pts for a full star player out.
    """
    return round(-impact_score * 4.0, 2)


# ─────────────────────────────────────────────
# LINE MOVEMENT
# ─────────────────────────────────────────────

def fetch_line_movement(league: str) -> dict:
    """
    Returns dict of {team_name: LineMovement}
    Uses The Odds API free tier.
    """
    if not ODDS_API_KEY or ODDS_API_KEY == "YOUR_ODDS_API_KEY_HERE":
        return {}

    sport_key = ODDS_API_SPORT_KEYS.get(league)
    if not sport_key:
        return {}

    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    "us",
        "markets":    "h2h",
        "oddsFormat": "american",
        "bookmakers": "draftkings,fanduel,betmgm",
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        games = resp.json()
    except Exception as e:
        print(f"  [Intel] Line movement fetch error: {e}")
        return {}

    movements = {}

    for game in games:
        bookmakers = game.get("bookmakers", [])
        if not bookmakers:
            continue

        team_odds = {}
        for book in bookmakers:
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    team  = outcome.get("name")
                    price = outcome.get("price", -110)
                    if team not in team_odds or price > team_odds[team]:
                        team_odds[team] = price

        for team, current_odds in team_odds.items():
            movements[team] = LineMovement(
                team         = team,
                opening_odds = int(current_odds),
                current_odds = int(current_odds),
            )

    return movements
# ─────────────────────────────────────────────
# INTEL SUMMARY FOR A MATCHUP
# ─────────────────────────────────────────────

def get_matchup_intel(home_team: str, away_team: str, league: str) -> dict:
    """
    Main function called by nba_wnba_predict.py before building alert.
    Returns intel dict with injury adjustments and line movement.
    """
    injuries  = fetch_injuries(league)
    movements = fetch_line_movement(league)

    # Injuries
    home_impact, home_inj = get_team_injury_impact(home_team, injuries)
    away_impact, away_inj = get_team_injury_impact(away_team, injuries)
    home_inj_adj = injury_adj_pts(home_impact)
    away_inj_adj = injury_adj_pts(away_impact)

    # Line movement
    home_move = movements.get(home_team)
    away_move = movements.get(away_team)

    return {
        "home_injury_adj":    home_inj_adj,
        "away_injury_adj":    away_inj_adj,
        "home_injuries":      home_inj,
        "away_injuries":      away_inj,
        "home_line_movement": home_move,
        "away_line_movement": away_move,
        "opening_home_odds":  home_move.opening_odds if home_move else None,
        "opening_away_odds":  away_move.opening_odds if away_move else None,
    }


def format_intel_summary(intel: dict, home_team: str, away_team: str) -> str:
    """Returns a formatted intel block to print below each alert."""
    lines = ["\n  📋 INTEL"]

    # Injuries
    for team, inj_list, adj in [
        (home_team, intel["home_injuries"], intel["home_injury_adj"]),
        (away_team, intel["away_injuries"], intel["away_injury_adj"]),
    ]:
        if inj_list:
            lines.append(f"  {team} injuries (adj: {adj:+.1f} pts):")
            for inj in inj_list:
                lines.append(f"    • {inj.player} ({inj.position}) — {inj.status}")
        else:
            lines.append(f"  {team}: No significant injuries reported")

    # Line movement
    for move in [intel["home_line_movement"], intel["away_line_movement"]]:
        if move and abs(move.movement) >= 5:
            lines.append(f"  Line: {move}")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# STANDALONE RUNNER
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    league = sys.argv[1].upper() if len(sys.argv) > 1 else "NBA"

    print(f"\n{'═'*60}")
    print(f"  📋 {league} INTEL FEED  |  Culture & Pulse Analytics")
    print(f"  {datetime.now().strftime('%A, %B %d %Y %I:%M %p')}")
    print(f"{'═'*60}")

    # Injuries
    print(f"\n  INJURY REPORT")
    print(f"  {'─'*40}")
    injuries = fetch_injuries(league)
    if injuries:
        for team, reports in sorted(injuries.items()):
            significant = [r for r in reports if r.impact >= 0.3]
            if significant:
                print(f"\n  {team}:")
                for r in significant:
                    print(f"    • {r.player} ({r.position}) — {r.status}")
                    if r.description:
                        print(f"      {r.description}")
    else:
        print("  No injury data available.")

    # Line movement
    print(f"\n  LINE MOVEMENT")
    print(f"  {'─'*40}")
    if not ODDS_API_KEY or ODDS_API_KEY == "4715e62920e940cec7ec335194cf5e2a":
        print("  Add your Odds API key to intel_feed.py to enable line movement.")
        print("  Free key at: https://the-odds-api.com")
    else:
        movements = fetch_line_movement(league)
        if movements:
            for team, move in sorted(movements.items()):
                if abs(move.movement) >= 5:
                    print(f"  {move}")
        else:
            print("  No significant line movement detected.")

    print()
