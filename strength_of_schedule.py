"""
strength_of_schedule.py — Culture & Pulse Analytics
====================================================
Standalone analytics engine — same pattern as team_form_engine.py and
performance_tracker.py: dynamic queries, no new writes, returns plain
dicts only. Sits between elo_ratings.py and ranking_engine.py:

    results --> elo_ratings.py --> strength_of_schedule.py --> ranking_engine.py

Responsibility: "how strong were this team's opponents, actually?"
Nothing more. It does NOT decide how much to trust its own output —
that judgment (reliability weighting, blending into a power score)
belongs in ranking_engine.py, same separation already applied to
elo_ratings.py (rating engine, not a trust engine).

IMPORTANT — hindsight-bias guard: opponent strength is measured using
each opponent's Elo AT THE TIME of that specific matchup
(elo_history.elo_before), not the opponent's current/final Elo. Using
current Elo would silently reintroduce the exact problem the Valkyries
check surfaced (2026-07-11) — a team that later lost several games
looks "weak" in today's ratings even though it wasn't provably weak on
the day it was played. elo_history already stores the pre-game
snapshot for both sides, so this comes for free without extra queries
against results.

Consequence of this design: a team with very few elo_history rows
(early in a fresh backfill) will have an equally thin SOS sample. This
file doesn't gate on that — ranking_engine.py's reliability weighting
is the right place to decide how much to trust a thin sample, for both
Elo and SOS together, not two separate ad-hoc thresholds.

Usage:
    py strength_of_schedule.py
    (prints a small validation block — see bottom of file)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn


def _norm_sport(sport):
    return sport.lower() if sport else None


def _opponent_elo_snapshots(team: str, sport: str = None, date_range: tuple = None) -> list:
    """Every game this team appears in elo_history, with the OPPONENT's
    elo_before value (the opponent's rating AT THE TIME of that game,
    not today). Most recent first."""
    sport = _norm_sport(sport)
    conn = get_conn()
    c = conn.cursor()

    where = "(home_team = ? OR away_team = ?)"
    params = [team, team]
    if sport:
        where += " AND sport = ?"
        params.append(sport)
    if date_range:
        where += " AND date BETWEEN ? AND ?"
        params.extend(date_range)

    c.execute(f"""
        SELECT date, home_team, away_team, home_elo_before, away_elo_before, winner
        FROM elo_history
        WHERE {where}
        ORDER BY date DESC, id DESC
    """, params)
    rows = c.fetchall()
    conn.close()

    out = []
    for r in rows:
        is_home = r["home_team"] == team
        opponent = r["away_team"] if is_home else r["home_team"]
        opponent_elo_at_time = r["away_elo_before"] if is_home else r["home_elo_before"]
        result = "W" if r["winner"] == team else "L"
        if opponent_elo_at_time is None:
            continue
        out.append({
            "date": r["date"],
            "opponent": opponent,
            "opponent_elo_at_time": opponent_elo_at_time,
            "result": result,
        })
    return out


def get_strength_of_schedule(team: str, sport: str = None, min_games: int = 3, date_range: tuple = None) -> dict:
    """Average opponent Elo (at time of matchup), plus a wins/losses vs
    above/below-average-opponent split. Returns insufficient_sample=True
    rather than a misleading SOS off a tiny sample — same threshold
    convention as team_form_engine.py."""
    games = _opponent_elo_snapshots(team, sport=sport, date_range=date_range)
    games_tracked = len(games)

    if games_tracked < min_games:
        return {"team": team, "sport": sport, "games_tracked": games_tracked, "insufficient_sample": True}

    opponent_elos = [g["opponent_elo_at_time"] for g in games]
    avg_opponent_elo = round(sum(opponent_elos) / len(opponent_elos), 1)

    wins_vs_above_avg = sum(1 for g in games if g["result"] == "W" and g["opponent_elo_at_time"] >= 1500)
    games_vs_above_avg = sum(1 for g in games if g["opponent_elo_at_time"] >= 1500)

    return {
        "team": team,
        "sport": sport,
        "games_tracked": games_tracked,
        "avg_opponent_elo": avg_opponent_elo,
        "schedule_difficulty": round(avg_opponent_elo - 1500, 1),
        "toughest_opponent": max(games, key=lambda g: g["opponent_elo_at_time"]),
        "weakest_opponent": min(games, key=lambda g: g["opponent_elo_at_time"]),
        "record_vs_above_avg_opponents": f"{wins_vs_above_avg}-{games_vs_above_avg - wins_vs_above_avg}",
        "insufficient_sample": False,
    }


def _all_teams(sport: str = None) -> list:
    sport = _norm_sport(sport)
    conn = get_conn()
    c = conn.cursor()
    if sport:
        c.execute("""
            SELECT DISTINCT team FROM (
                SELECT home_team AS team FROM elo_history WHERE sport = ?
                UNION
                SELECT away_team AS team FROM elo_history WHERE sport = ?
            )
        """, [sport, sport])
    else:
        c.execute("""
            SELECT DISTINCT team FROM (
                SELECT home_team AS team FROM elo_history
                UNION
                SELECT away_team AS team FROM elo_history
            )
        """)
    rows = c.fetchall()
    conn.close()
    return [r["team"] for r in rows]


def get_sos_rankings(sport: str = None, min_games: int = 3, hardest_first: bool = True) -> list:
    """All teams ranked by strength of schedule. hardest_first=True
    sorts toughest schedule first (highest avg_opponent_elo)."""
    teams = _all_teams(sport)
    profiles = []
    for team in teams:
        p = get_strength_of_schedule(team, sport=sport, min_games=min_games)
        if not p.get("insufficient_sample"):
            profiles.append(p)
    profiles.sort(key=lambda p: p["avg_opponent_elo"], reverse=hardest_first)
    return profiles


if __name__ == "__main__":
    print(get_strength_of_schedule("Golden State Valkyries", "wnba"))
    print(get_strength_of_schedule("Minnesota Lynx", "wnba"))
    for p in get_sos_rankings("wnba"):
        print(f"{p['team']:<28} avg_opp_elo={p['avg_opponent_elo']:<8} games={p['games_tracked']}")
