"""
team_form_engine.py — Culture & Pulse Analytics
====================================================
(renamed from streak_engine.py, 2026-07-11 — "Streak Finder" stays the
feature/content name, but the engine underneath does more than
streaks: streak, last 5/10, win %, model context, last game date, and
recent game history with opponent. This is infrastructure, not a
feature — it sits in the dependency chain between performance_tracker.py
and the future power_rankings.py / team_profile.py / matchup_analyzer.py
modules.)

Standalone analytics engine — same pattern as performance_tracker.py:
dynamic queries against predictions/results, no new table, no
materialized aggregation yet (materialize into team_stats only if/when
Power Rankings needs the speed, per the 2026-07-11 roadmap decision).

Responsibilities: query predictions/results, normalize team-centric
results, calculate streaks/rolling records/model stats. Returns plain
dicts only — no UI cards, no charts, no social formatting, no writes
to the database. Streamlit/content layers consume this, not the other
way around.

Source of truth: results.actual_winner vs home_team/away_team — NOT
results.correct. results.correct measures whether the MODEL'S pick
was right, not whether a given team won. A team can go 5-0 on the
field while the model faded them every time; that's a real, useful
signal and this file has to be able to show it. Model-pick-correctness
streaks are a different question, already covered by
performance_tracker.py's confidence/ROI functions.

edge / model_prob handling: these are only populated on a game-result
row when predictions.predicted_winner == the team in question — i.e.
the model's number was actually FOR this team. If the model picked
the opponent, edge/model_prob are left as None for that row rather
than inverted or guessed; averaging an inverted probability would
misrepresent what the model actually said. Do not "fix" this by
flipping probability/edge for the non-picked side — that fabricates a
prediction the model never made.

Data-quality guard: a result row is only counted for a team if
actual_winner exactly matches home_team or away_team. If a future data
feed ever writes a differently-formatted winner string (e.g. "Alabama
Crimson Tide" vs "Alabama"), that row is skipped rather than silently
misclassified as a loss for both teams.

v1 scope: no ATS/spread streak, no O/U streak — those columns don't
exist on results yet (confirmed via check_team_integrity.py + schema
review, 2026-07-11). Add once spread/total outcomes are logged.

Note: league-phase filtering (Summer League, preseason, spring
training tagged under a sport's normal season) is deliberately NOT
handled here — this engine doesn't know league rules. That belongs in
a future competition_filter.py / league_context.py. See roadmap notes.

Usage:
    py team_form_engine.py
    (prints a small validation block — see bottom of file)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from elo_ratings import GAME_RESULTS_SOURCE


def _norm_sport(sport):
    """sport is stored lowercase throughout the codebase (nfl, wnba,
    mlb, cfb, nba...) — normalize here so callers don't have to
    remember that, since every other engine file assumes it."""
    return sport.lower() if sport else None


def _team_game_rows(team: str, sport: str = None, date_range: tuple = None) -> list:
    """Team-centric list of every real game involving `team`, most
    recent first: {date, game, sport, result ("W"/"L"), edge, model_prob}.

    CHANGED 2026-07-11 (round 2): `results` was confirmed to be a
    betting ledger (only games the model actually predicted), not a
    full game log — see elo_ratings.py's GAME_RESULTS_SOURCE docstring
    for the full investigation. When a sport has a derived
    team_game_results table (currently WNBA only, via
    wnba_game_results.py), this reads from that instead — real ESPN
    outcomes, independent of whether the model ever predicted the
    game. team_game_results has no FK to predictions (it's not built
    from predictions at all), so edge/model_prob are picked up via a
    separate LEFT JOIN matched on (date, home_team, away_team) instead
    of the old prediction_id FK join — same "only populate if the
    model actually picked THIS team" rule as before, just a different
    join path to get there. Sports without a mapped source still fall
    back to the old results-based query, unchanged."""
    sport = _norm_sport(sport)
    conn = get_conn()
    c = conn.cursor()

    source_table = GAME_RESULTS_SOURCE.get(sport)

    if source_table:
        where = "(g.home_team = ? OR g.away_team = ?)"
        params = [team, team]
        if sport:
            where += " AND g.sport = ?"
            params.append(sport)
        if date_range:
            where += " AND g.date BETWEEN ? AND ?"
            params.extend(date_range)

        c.execute(f"""
            SELECT g.date, g.sport, g.home_team, g.away_team, g.winner AS actual_winner,
                   p.predicted_winner, p.model_prob, p.edge
            FROM {source_table} g
            LEFT JOIN results r ON r.date = g.date AND r.home_team = g.home_team
                                AND r.away_team = g.away_team AND r.sport = g.sport
            LEFT JOIN predictions p ON r.prediction_id = p.id
            WHERE {where}
            ORDER BY g.date DESC, g.id DESC
        """, params)
        rows = c.fetchall()
        conn.close()

        out = []
        for r in rows:
            result = "W" if r["actual_winner"] == team else "L"
            opponent = r["away_team"] if r["home_team"] == team else r["home_team"]
            picked_this_team = r["predicted_winner"] == team
            out.append({
                "date": r["date"],
                "game": f"{r['away_team']} @ {r['home_team']}",
                "opponent": opponent,
                "sport": r["sport"],
                "result": result,
                "edge": r["edge"] if picked_this_team else None,
                "model_prob": r["model_prob"] if picked_this_team else None,
            })
        return out

    # Fallback: no games-truth-layer table for this sport yet — old
    # results-based query, unchanged from before.
    where = "(r.home_team = ? OR r.away_team = ?)"
    params = [team, team]
    if sport:
        where += " AND r.sport = ?"
        params.append(sport)
    if date_range:
        where += " AND r.date BETWEEN ? AND ?"
        params.extend(date_range)

    c.execute(f"""
        SELECT r.date, r.game, r.sport, r.home_team, r.away_team,
               r.actual_winner, p.predicted_winner, p.model_prob, p.edge
        FROM results r
        LEFT JOIN predictions p ON r.prediction_id = p.id
        WHERE {where} AND r.actual_winner IS NOT NULL
        ORDER BY r.date DESC, r.id DESC
    """, params)
    rows = c.fetchall()
    conn.close()

    out = []
    for r in rows:
        if r["actual_winner"] not in (r["home_team"], r["away_team"]):
            continue  # actual_winner doesn't match either team string — skip rather than misclassify
        result = "W" if r["actual_winner"] == team else "L"
        opponent = r["away_team"] if r["home_team"] == team else r["home_team"]
        picked_this_team = r["predicted_winner"] == team
        out.append({
            "date": r["date"],
            "game": r["game"],
            "opponent": opponent,
            "sport": r["sport"],
            "result": result,
            "edge": r["edge"] if picked_this_team else None,
            "model_prob": r["model_prob"] if picked_this_team else None,
        })
    return out


def _current_streak(games: list) -> dict:
    """games must be most-recent-first. Walks from the top counting
    consecutive identical W/L results."""
    if not games:
        return {"type": None, "length": 0}
    result = games[0]["result"]
    length = 0
    for g in games:
        if g["result"] == result:
            length += 1
        else:
            break
    return {"type": "win" if result == "W" else "loss", "length": length}


def _record(games: list) -> dict:
    wins = sum(1 for g in games if g["result"] == "W")
    return {"wins": wins, "losses": len(games) - wins, "record": f"{wins}-{len(games) - wins}"}


def get_team_form(team: str, sport: str = None, min_games: int = 3, date_range: tuple = None) -> dict:
    """Full streak/form profile for one team's actual game results.
    Returns insufficient_sample=True rather than a misleading streak
    off a tiny sample.

    Includes recent_games (last 10, most recent first) for downstream
    consumers (Team Profile, Power Rankings) that need the underlying
    timeline — e.g. "is the streak inflated by weak opponents", "is
    the team improving" — not just the summary numbers."""
    games = _team_game_rows(team, sport=sport, date_range=date_range)
    games_tracked = len(games)

    if games_tracked < min_games:
        return {
            "team": team,
            "sport": sport,
            "games_tracked": games_tracked,
            "insufficient_sample": True,
        }

    wins_total = sum(1 for g in games if g["result"] == "W")
    edges = [g["edge"] for g in games if g["edge"] is not None]
    probs = [g["model_prob"] for g in games if g["model_prob"] is not None]

    return {
        "team": team,
        "sport": sport,
        "games_tracked": games_tracked,
        "current_streak": _current_streak(games),
        "last_5": _record(games[:5]),
        "last_10": _record(games[:10]),
        "win_percentage": round(wins_total / games_tracked, 3),
        "avg_edge": round(sum(edges) / len(edges), 3) if edges else None,
        "avg_model_probability": round(sum(probs) / len(probs), 3) if probs else None,
        "last_game_date": games[0]["date"],
        "recent_games": games[:10],
        "insufficient_sample": False,
    }


def _all_teams(sport: str = None) -> list:
    sport = _norm_sport(sport)
    conn = get_conn()
    c = conn.cursor()
    source_table = GAME_RESULTS_SOURCE.get(sport) if sport else None
    if source_table:
        c.execute(f"""
            SELECT DISTINCT team FROM (
                SELECT home_team AS team FROM {source_table} WHERE sport = ? AND home_team != ''
                UNION
                SELECT away_team AS team FROM {source_table} WHERE sport = ? AND away_team != ''
            )
        """, [sport, sport])
    elif sport:
        c.execute("""
            SELECT DISTINCT team FROM (
                SELECT home_team AS team FROM results WHERE sport = ? AND home_team != ''
                UNION
                SELECT away_team AS team FROM results WHERE sport = ? AND away_team != ''
            )
        """, [sport, sport])
    else:
        c.execute("""
            SELECT DISTINCT team FROM (
                SELECT home_team AS team FROM results WHERE home_team != ''
                UNION
                SELECT away_team AS team FROM results WHERE away_team != ''
            )
        """)
    rows = c.fetchall()
    conn.close()
    return [r["team"] for r in rows]


def _scan_teams(sport: str, min_games: int, limit: int, date_range: tuple, streak_type: str) -> list:
    """Shared implementation for get_hot_teams/get_cold_teams.
    streak_type is 'win' or 'loss'."""
    teams = _all_teams(sport)
    profiles = []
    for team in teams:
        p = get_team_form(team, sport=sport, min_games=min_games, date_range=date_range)
        if p.get("insufficient_sample"):
            continue
        if p["current_streak"]["type"] == streak_type and p["current_streak"]["length"] >= 2:
            profiles.append(p)

    profiles.sort(
        key=lambda p: (p["current_streak"]["length"], p["win_percentage"], p["games_tracked"]),
        reverse=True,
    )

    letter = "W" if streak_type == "win" else "L"
    return [
        {
            "team": p["team"],
            "streak": f"{letter}{p['current_streak']['length']}",
            "win_pct": p["win_percentage"],
            "avg_edge": p["avg_edge"],
        }
        for p in profiles[:limit]
    ]


def get_hot_teams(sport: str = None, min_games: int = 3, limit: int = 10, date_range: tuple = None) -> list:
    """Teams currently on a real win streak. Sorted by streak length,
    then win %, then sample size. Named "hot teams" rather than "hot
    streaks" deliberately — this scan currently sorts on streak
    length, but "hot" is meant to extend later (model edge trending
    up, ATS streak, efficiency surge) without another rename."""
    return _scan_teams(sport, min_games, limit, date_range, "win")


def get_cold_teams(sport: str = None, min_games: int = 3, limit: int = 10, date_range: tuple = None) -> list:
    """Teams currently on a real loss streak — a live fade signal.
    Sorted by streak length, then win %, then sample size."""
    return _scan_teams(sport, min_games, limit, date_range, "loss")


if __name__ == "__main__":
    print(get_team_form("Alabama"))
    print(get_hot_teams("nfl"))
    print(get_cold_teams("nba"))
