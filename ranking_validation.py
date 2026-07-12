"""
ranking_validation.py — Culture & Pulse Analytics
====================================================
Compares ranking_engine.py's Power Rank against two independent,
directly-observable truths pulled straight from team_game_results:
actual win-loss record and average point differential. Neither of
these numbers comes from Elo, SOS, or any model — they're just
"add up what actually happened."

Purpose: find out where the model's opinion (Power Rank) disagrees
with reality (record/point-diff rank), rather than tuning weights on
a hunch. Per the 2026-07-11 agreement: don't touch normalization or
weights again until this validation data says where it's actually
wrong.

This does NOT replace an eye test — a team can legitimately have a
worse record than its underlying quality (bad luck in close games,
tough early schedule) and Power Rank disagreeing with record isn't
automatically a bug. It's the starting point for asking why.

Usage:
    py ranking_validation.py wnba
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from ranking_engine import get_rankings


def get_actual_record_and_diff(team: str, sport: str) -> dict:
    """Real win-loss record and average point differential, computed
    directly from team_game_results — no model, no Elo, no weighting.
    Returns None if this sport has no team_game_results table (same
    GAME_RESULTS_SOURCE gap as elo_ratings.py/team_form_engine.py)."""
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT home_team, away_team, home_score, away_score, winner
            FROM team_game_results
            WHERE (home_team = ? OR away_team = ?) AND sport = ?
        """, (team, team, sport))
        rows = c.fetchall()
    except Exception:
        conn.close()
        return None
    conn.close()

    if not rows:
        return None

    wins = 0
    point_diffs = []
    for r in rows:
        is_home = r["home_team"] == team
        team_score = r["home_score"] if is_home else r["away_score"]
        opp_score = r["away_score"] if is_home else r["home_score"]
        point_diffs.append(team_score - opp_score)
        if r["winner"] == team:
            wins += 1

    games = len(rows)
    return {
        "games": games,
        "wins": wins,
        "losses": games - wins,
        "record": f"{wins}-{games - wins}",
        "win_pct": round(wins / games, 3),
        "avg_point_diff": round(sum(point_diffs) / games, 1),
    }


def get_validation_report(sport: str) -> list:
    """For every team in ranking_engine.py's output, attaches actual
    record/point-diff and a separately-computed 'record rank' (sorted
    by win_pct, then point diff as tiebreak) so Power Rank and Record
    Rank can be compared directly."""
    rankings = get_rankings(sport)

    report = []
    for r in rankings:
        actual = get_actual_record_and_diff(r["team"], sport)
        if actual is None:
            continue
        report.append({
            "team": r["team"],
            "power_rank": r["rank"],
            "power_score": r["power_score"],
            "record": actual["record"],
            "win_pct": actual["win_pct"],
            "avg_point_diff": actual["avg_point_diff"],
        })

    # Independent record-based ranking — sorted by win_pct, then point
    # diff as tiebreak, entirely separate from power_score's ordering.
    by_record = sorted(report, key=lambda t: (t["win_pct"], t["avg_point_diff"]), reverse=True)
    record_rank_map = {t["team"]: i + 1 for i, t in enumerate(by_record)}

    for t in report:
        t["record_rank"] = record_rank_map[t["team"]]
        t["rank_difference"] = t["record_rank"] - t["power_rank"]  # positive = Power Rank is HIGHER than record rank

    return report


if __name__ == "__main__":
    sport_arg = sys.argv[1] if len(sys.argv) > 1 else "wnba"
    report = get_validation_report(sport_arg)

    print(f"\n{'='*90}")
    print(f"  {sport_arg.upper()} POWER RANK vs ACTUAL RECORD")
    print(f"{'='*90}")
    print(f"  {'Team':<24} {'Power':>6} {'Record':>7} {'Rec.Rk':>7} {'PtDiff':>7} {'Diff':>6}")
    print(f"  {'-'*24} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*6}")
    for t in sorted(report, key=lambda x: x["power_rank"]):
        diff_flag = ""
        if abs(t["rank_difference"]) >= 3:
            diff_flag = "  <-- model disagrees with record by 3+ spots"
        print(f"  {t['team']:<24} {t['power_rank']:>6} {t['record']:>7} "
              f"{t['record_rank']:>7} {t['avg_point_diff']:>+7} {t['rank_difference']:>+6}{diff_flag}")
    print(f"\n{'='*90}")
    print("  Positive Diff = Power Rank ranks them HIGHER than their record alone would.")
    print("  Negative Diff = Power Rank ranks them LOWER than their record alone would.")
    print("  Neither is automatically wrong — this is where to start asking why.")
    print(f"{'='*90}\n")
