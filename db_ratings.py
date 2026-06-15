"""
db_ratings.py — Culture & Pulse Analytics
Pulls team net ratings from cp_analytics.db.
Used as fallback when live ESPN/NBA.com ratings are unavailable.
Priority: Current season → Last 3 seasons weighted average
"""

import os
from database import get_conn

CURRENT_YEAR = 2026


def get_db_net_rating(team_name: str, sport: str) -> float:
    """
    Returns net rating for a team from the DB.
    Weights current season heavily, blends in last 2 seasons.
    Returns 0.0 if team not found.
    """
    conn = get_conn()
    c    = conn.cursor()

    sport = sport.lower()

    # Pull last 3 seasons
    c.execute("""
        SELECT season, wins, losses, net_rating, pts_per_game, pts_allowed
        FROM team_stats
        WHERE sport = ? AND team_name = ?
        ORDER BY season DESC
        LIMIT 3
    """, (sport, team_name))

    rows = c.fetchall()
    conn.close()

    if not rows:
        return 0.0

    # If net_rating is stored use it directly
    # Otherwise calculate from pts_per_game - pts_allowed
    weighted_sum   = 0.0
    weight_total   = 0.0
    weights        = [0.6, 0.3, 0.1]  # current, last, 2 seasons ago

    for i, row in enumerate(rows):
        net_rating   = row["net_rating"]
        pts_per_game = row["pts_per_game"]
        pts_allowed  = row["pts_allowed"]
        wins         = row["wins"]
        losses       = row["losses"]
        games        = wins + losses

        if games == 0:
            continue

        # Use stored net rating if available, otherwise derive from pts
        if net_rating and net_rating != 0.0:
            rating = net_rating
        elif pts_per_game and pts_allowed:
            rating = pts_per_game - pts_allowed
        else:
            # Derive from win % as proxy
            win_pct = wins / games if games > 0 else 0.5
            rating  = (win_pct - 0.5) * 20  # scale to approx net rating range
            
        w = weights[i] if i < len(weights) else 0.05
        weighted_sum  += rating * w
        weight_total  += w

    if weight_total == 0:
        return 0.0

    return round(weighted_sum / weight_total, 2)


def get_db_record(team_name: str, sport: str) -> tuple:
    """
    Returns (wins, losses) for current season from DB.
    Returns (0, 0) if not found.
    """
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT wins, losses FROM team_stats
        WHERE sport = ? AND team_name = ?
        ORDER BY season DESC
        LIMIT 1
    """, (sport.lower(), team_name))

    row = c.fetchone()
    conn.close()

    if not row:
        return (0, 0)

    return (row["wins"], row["losses"])


def get_all_db_ratings(sport: str) -> dict:
    """
    Returns dict of {team_name: net_rating} for all teams in a sport.
    Used to replace static rating dicts entirely.
    """
    conn = get_conn()
    c    = conn.cursor()

    # Get all unique team names for this sport
    c.execute("""
        SELECT DISTINCT team_name FROM team_stats
        WHERE sport = ?
    """, (sport.lower(),))

    teams = [row["team_name"] for row in c.fetchall()]
    conn.close()

    ratings = {}
    for team in teams:
        rating = get_db_net_rating(team, sport)
        if rating != 0.0:
            ratings[team] = rating

    return ratings


def get_head_to_head_edge(home_team: str, away_team: str, sport: str) -> float:
    """
    Returns head-to-head win rate for home team vs away team.
    Returns 0.0 if insufficient history.
    Positive = home team historically dominates, negative = away team dominates.
    """
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT winner, home_team, away_team
        FROM head_to_head
        WHERE sport = ?
        AND (
            (home_team = ? AND away_team = ?)
            OR
            (home_team = ? AND away_team = ?)
        )
        ORDER BY date DESC
        LIMIT 20
    """, (sport.lower(), home_team, away_team, away_team, home_team))

    rows = c.fetchall()
    conn.close()

    if len(rows) < 3:
        return 0.0  # Not enough history

    home_wins = sum(1 for r in rows if r["winner"] == home_team)
    total     = len(rows)
    win_rate  = home_wins / total

    # Convert to edge adjustment (-2.0 to +2.0 points)
    edge = (win_rate - 0.5) * 4.0
    return round(edge, 2)


if __name__ == "__main__":
    # Test it
    sports = ["nba", "wnba", "nfl", "ncaab", "ncaaf"]
    for sport in sports:
        ratings = get_all_db_ratings(sport)
        print(f"\n{sport.upper()} — {len(ratings)} teams in DB")
        top = sorted(ratings.items(), key=lambda x: x[1], reverse=True)[:5]
        for team, rating in top:
            sign = "+" if rating >= 0 else ""
            print(f"  {team:<35} {sign}{rating}")