"""
check_elo_history.py - Culture & Pulse Analytics

Validates a specific team's Elo trajectory game-by-game, to sanity
check outliers before trusting them downstream (e.g. Golden State
Valkyries hitting 1684.1 after only 7 games — flagged 2026-07-11 as
worth verifying before building ranking_engine.py on top of it).

elo_history is stored per-GAME (home_team/away_team + both sides'
before/after), not per-team-row — this script derives the team's own
perspective (opponent, elo_before, elo_after, elo_change) from
whichever side of each row the team was on.

Read-only. Safe to run any time.

Usage:
    python check_elo_history.py "Golden State Valkyries" wnba
"""

import sys
from database import get_conn

DEFAULT_TEAM = "Golden State Valkyries"
DEFAULT_SPORT = "wnba"


def run(team: str, sport: str):
    conn = get_conn()
    c = conn.cursor()

    print("=" * 70)
    print(f"  Elo history: {team} ({sport.upper()})")
    print("=" * 70)

    c.execute("""
        SELECT date, home_team, away_team,
               home_elo_before, away_elo_before,
               home_elo_after, away_elo_after, winner
        FROM elo_history
        WHERE (home_team = ? OR away_team = ?) AND sport = ?
        ORDER BY date ASC
    """, (team, team, sport))
    rows = c.fetchall()

    if not rows:
        print("  No elo_history rows found for this team/sport.")
        print("  (Check exact spelling matches the team-name strings")
        print("   confirmed in check_team_integrity.py's distinct list.)")
    else:
        for r in rows:
            g = dict(r)
            is_home = g["home_team"] == team
            opponent = g["away_team"] if is_home else g["home_team"]
            elo_before = g["home_elo_before"] if is_home else g["away_elo_before"]
            elo_after = g["home_elo_after"] if is_home else g["away_elo_after"]
            change = round(elo_after - elo_before, 1) if elo_before is not None and elo_after is not None else None
            result = "W" if g["winner"] == team else "L"
            sign = "+" if (change or 0) >= 0 else ""
            print(f"  {g['date']:<12} {result} vs {opponent:<25} "
                  f"{elo_before:>8} -> {elo_after:>8}  ({sign}{change})")

    print()
    print("=" * 70)
    print("  Underlying results (real scores this Elo was built from)")
    print("=" * 70)

    c.execute("""
        SELECT date, home_team, away_team, home_score, away_score, actual_winner
        FROM results
        WHERE (home_team = ? OR away_team = ?) AND sport = ?
        ORDER BY date ASC
    """, (team, team, sport))
    game_rows = c.fetchall()

    if not game_rows:
        print("  No results rows found for this team/sport.")
    else:
        for r in game_rows:
            g = dict(r)
            if g["home_score"] is None or g["away_score"] is None:
                print(f"  {g['date']:<12} vs (score missing — skipped by Elo backfill)")
                continue
            opp = g["away_team"] if g["home_team"] == team else g["home_team"]
            margin = (g["home_score"] - g["away_score"]) if g["home_team"] == team \
                else (g["away_score"] - g["home_score"])
            print(f"  {g['date']:<12} vs {opp:<25} "
                  f"score {g['home_score']}-{g['away_score']}  "
                  f"winner={g['actual_winner']:<25} margin={margin:+d}")

    conn.close()

    print()
    print("=" * 70)
    print("What to look for:")
    print("  - Large per-game elo_change values on blowout wins against")
    print("    strong opponents are expected early in a season, when the")
    print("    dynamic K-factor is still high for low games-played counts")
    print("    (that's the system working as designed, not a bug)")
    print("  - Whether the opponents beaten were themselves rated highly")
    print("    (beating a weak team shouldn't move Elo much even with MOV)")
    print("  - Whether the underlying `results` scores/margins actually")
    print("    support a run this strong, or look inconsistent/wrong")
    print("=" * 70)


if __name__ == "__main__":
    team = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEAM
    sport = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SPORT
    run(team, sport)
