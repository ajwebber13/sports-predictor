"""
check_game_log_coverage.py - Culture & Pulse Analytics

Audits wnba_game_log (player-level box scores) as a candidate
replacement source for elo_ratings.py / ranking_engine.py, since
results was confirmed structurally limited to games the model
actually predicted (2026-07-11 finding — a 61-game "season" when
ESPN standings imply 170+ games played).

wnba_game_log has no direct team-level winner/score columns (it's
per-player: pts/reb/ast/stl/blk), but team score is derivable via
SUM(pts) GROUP BY date, team_name. This script checks whether that's
actually usable: how many distinct game-dates are covered, whether
coverage is anywhere close to a real season, and does a couple of
derived-score sanity checks against known games.

Read-only. Safe to run any time.
"""

from database import get_conn


def run():
    conn = get_conn()
    c = conn.cursor()

    print("=" * 70)
    print("1. wnba_game_log overview")
    print("=" * 70)
    c.execute("""
        SELECT COUNT(*) AS total_rows,
               COUNT(DISTINCT date) AS distinct_dates,
               COUNT(DISTINCT player_name) AS distinct_players,
               COUNT(DISTINCT team_name) AS distinct_teams,
               MIN(date) AS earliest,
               MAX(date) AS latest
        FROM wnba_game_log
    """)
    row = dict(c.fetchone())
    for k, v in row.items():
        print(f"  {k}: {v}")

    print()
    print("=" * 70)
    print("2. rows per distinct date (sample — first 15 dates)")
    print("=" * 70)
    c.execute("""
        SELECT date, COUNT(DISTINCT team_name) AS teams_on_date,
               COUNT(DISTINCT player_name) AS players_on_date
        FROM wnba_game_log
        GROUP BY date
        ORDER BY date ASC
        LIMIT 15
    """)
    for r in c.fetchall():
        d = dict(r)
        print(f"  {d['date']:<12} teams={d['teams_on_date']:<4} players={d['players_on_date']}")

    print()
    print("=" * 70)
    print("3. compare distinct game-dates to results table (the confidence-filtered log)")
    print("=" * 70)
    c.execute("SELECT COUNT(DISTINCT date) AS d, MIN(date) AS mn, MAX(date) AS mx FROM results WHERE sport = 'wnba'")
    r = dict(c.fetchone())
    print(f"  results (wnba):      distinct_dates={r['d']}  range={r['mn']} to {r['mx']}")
    c.execute("SELECT COUNT(DISTINCT date) AS d, MIN(date) AS mn, MAX(date) AS mx FROM wnba_game_log")
    r = dict(c.fetchone())
    print(f"  wnba_game_log:       distinct_dates={r['d']}  range={r['mn']} to {r['mx']}")

    print()
    print("=" * 70)
    print("4. derived team score sanity check (SUM(pts) per team per date, 10 games)")
    print("=" * 70)
    c.execute("""
        SELECT date, team_name, SUM(pts) AS team_pts, COUNT(*) AS players_counted
        FROM wnba_game_log
        GROUP BY date, team_name
        ORDER BY date DESC
        LIMIT 20
    """)
    for r in c.fetchall():
        d = dict(r)
        print(f"  {d['date']:<12} {d['team_name']:<24} derived_pts={d['team_pts']:<6} (from {d['players_counted']} players)")

    conn.close()

    print()
    print("=" * 70)
    print("What to look for:")
    print("  - distinct_dates in wnba_game_log should be close to the number of")
    print("    days the WNBA season has actually been played, not a small fraction")
    print("  - derived team_pts values should look like real basketball scores")
    print("    (roughly 60-100), not suspiciously low (missing players/rows)")
    print("  - if wnba_game_log's distinct_dates is only slightly ahead of")
    print("    results', this table is ALSO incomplete and needs its own fix")
    print("    before it can replace results as Elo's source")
    print("=" * 70)


if __name__ == "__main__":
    run()
