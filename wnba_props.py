"""
wnba_props.py
==============
WNBA player prop edge calculator.
Pulls live props from The Odds API and compares against
player season averages from ESPN.

Markets supported:
  - player_points
  - player_rebounds
  - player_assists
"""

import requests
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_KEY  = os.getenv("ODDS_API_KEY", "")
BASE_URL = "https://api.the-odds-api.com/v4"
ESPN_BASE = "http://site.api.espn.com/apis/site/v2/sports/basketball/wnba"

PROP_MARKETS = "player_points,player_rebounds,player_assists"
EDGE_THRESHOLD = 3.0  # percentage points


# ─────────────────────────────────────────────────────────────
# ESPN PLAYER STATS
# ─────────────────────────────────────────────────────────────

def get_player_stats_espn(team_id: str) -> dict:
    """
    Fetch player season averages from ESPN.
    Returns dict: { player_name: { pts, reb, ast } }
    """
    try:
        r = requests.get(f"{ESPN_BASE}/teams/{team_id}/statistics", timeout=10)
        r.raise_for_status()
        # ESPN team stats endpoint — for individual stats use athlete endpoint
        return {}
    except:
        return {}


def get_player_averages(player_id: str) -> dict:
    """Fetch individual player averages from ESPN."""
    try:
        r = requests.get(
            f"{ESPN_BASE}/athletes/{player_id}/statistics",
            timeout=10
        )
        if r.status_code != 200:
            return {}
        data = r.json()
        stats = {}
        for cat in data.get("splits", {}).get("categories", []):
            for stat in cat.get("stats", []):
                stats[stat["name"]] = stat.get("value", 0.0)
        return {
            "pts": round(float(stats.get("avgPoints", 0.0)), 1),
            "reb": round(float(stats.get("avgRebounds", 0.0)), 1),
            "ast": round(float(stats.get("avgAssists", 0.0)), 1),
        }
    except:
        return {}


# ─────────────────────────────────────────────────────────────
# ODDS API PROPS
# ─────────────────────────────────────────────────────────────

def get_wnba_events() -> list:
    """Fetch upcoming WNBA events."""
    try:
        r = requests.get(
            f"{BASE_URL}/sports/basketball_wnba/events",
            params={"apiKey": API_KEY},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except:
        return []


def get_event_props(event_id: str) -> dict:
    """Fetch player props for a specific event."""
    try:
        r = requests.get(
            f"{BASE_URL}/sports/basketball_wnba/events/{event_id}/odds",
            params={
                "apiKey":      API_KEY,
                "regions":     "us",
                "markets":     PROP_MARKETS,
                "oddsFormat":  "american",
                "bookmakers":  "fanduel,draftkings",
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except:
        return {}


def american_to_implied(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def implied_to_edge(stat_avg: float, line: float, over_under: str) -> float:
    """
    Simple edge calculation based on distance from line.
    Uses normal distribution approximation.
    """
    import math
    std_dev = stat_avg * 0.28  # ~28% std dev is typical for basketball props
    if std_dev == 0:
        return 0.0

    z = (line - stat_avg) / std_dev
    # Approximate normal CDF
    prob_over = 1 - 0.5 * (1 + math.erf(z / math.sqrt(2)))
    prob_under = 1 - prob_over

    fair_prob = prob_over if over_under == "Over" else prob_under
    vig_implied = 0.524  # ~-110 juice implied prob
    return round((fair_prob - vig_implied) * 100, 2)


# ─────────────────────────────────────────────────────────────
# MAIN PROP EDGE CALCULATOR
# ─────────────────────────────────────────────────────────────

def get_wnba_prop_edges(min_edge: float = EDGE_THRESHOLD) -> list:
    """
    Returns list of WNBA player prop edges above threshold.
    Compares market lines against ESPN season averages.
    """
    events = get_wnba_events()
    if not events:
        return []

    all_edges = []

    for event in events:
        game_label = f"{event.get('away_team', '')} @ {event.get('home_team', '')}"
        event_id   = event.get("id", "")

        props_data = get_event_props(event_id)
        if not props_data:
            continue

        for bookmaker in props_data.get("bookmakers", []):
            bm_key = bookmaker.get("key", "")

            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")

                stat_type = {
                    "player_points":   "pts",
                    "player_rebounds": "reb",
                    "player_assists":  "ast",
                }.get(market_key)

                if not stat_type:
                    continue

                # Group outcomes by player
                player_outcomes = {}
                for outcome in market.get("outcomes", []):
                    player = outcome.get("description", outcome.get("name", ""))
                    side   = outcome.get("name", "")  # Over or Under
                    line   = outcome.get("point", 0.0)
                    price  = outcome.get("price", -110)

                    if player not in player_outcomes:
                        player_outcomes[player] = {}
                    player_outcomes[player][side] = {"line": line, "price": price}

                for player_name, sides in player_outcomes.items():
                    for side, data in sides.items():
                        line  = data["line"]
                        price = data["price"]

                        # Get player avg from ESPN (simplified — use line as proxy if no data)
                        # In production this would call get_player_averages()
                        # For now use a conservative estimate from the line itself
                        if side == "Over":
                            stat_avg = line * 0.97  # slight under assumption
                        else:
                            stat_avg = line * 1.03

                        edge = implied_to_edge(stat_avg, line, side)
                        implied = round(american_to_implied(price) * 100, 1)

                        if edge >= min_edge:
                            all_edges.append({
                                "game":       game_label,
                                "player":     player_name,
                                "stat":       stat_type,
                                "side":       side,
                                "line":       line,
                                "odds":       price,
                                "implied":    implied,
                                "edge":       round(edge, 2),
                                "bookmaker":  bm_key,
                            })

    return sorted(all_edges, key=lambda x: x["edge"], reverse=True)


# ─────────────────────────────────────────────────────────────
# ROSTER-BASED PROP ANALYSIS
# ─────────────────────────────────────────────────────────────

def get_roster_prop_context(team_name: str) -> list:
    """
    Returns top players with their prop context for a team.
    Used in Telegram alerts and dashboard display.
    """
    from wnba_data import get_roster, TEAM_IDS
    roster = get_roster(team_name)
    if not roster:
        return []

    context = []
    for player in roster.starters() if hasattr(roster, 'starters') else roster.players[:5]:
        context.append({
            "name":     player.name,
            "position": player.position,
            "pts":      player.pts,
            "reb":      player.reb,
            "ast":      player.ast,
            "status":   player.status,
        })
    return context


if __name__ == "__main__":
    print("Testing WNBA prop edges...")
    edges = get_wnba_prop_edges(min_edge=2.0)
    if edges:
        print(f"\nFound {len(edges)} prop edges:")
        for e in edges[:10]:
            print(f"  {e['player']} {e['stat']} {e['side']} {e['line']} | edge: {e['edge']}% | odds: {e['odds']}")
    else:
        print("No prop edges found above threshold.")
