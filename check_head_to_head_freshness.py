"""
check_head_to_head_freshness.py - Culture & Pulse Analytics

Checks whether head_to_head is current and complete, ahead of deciding
whether to reconnect elo_ratings.py to it or repoint Elo at `results`
instead. Read-only, safe to run any time.

Context (found via repo grep, 2026-07-11): every INSERT into
head_to_head lives in a manual/CLI backfill script (backfill.py,
backfill_h2h_wnba.py, hbcu_backfill.py) — none are called from any
GitHub Actions workflow, so nothing keeps this table current
automatically. backfill_head_to_head() also only samples ESPN's
scoreboard for the 1st and 15th of each month, not every day — so even
a "current" table built this way is a ~6%-of-games sample, not a full
game log. This script confirms both the staleness and the sample-rate
gap against `results`, which IS comprehensively populated by the live
pipeline.
"""

from database import get_conn


def run():
    conn = get_conn()
    c = conn.cursor()

    print("=" * 60)
    print("1. head_to_head overall")
    print("=" * 60)
    c.execute("""
        SELECT COUNT(*) AS total_games, MAX(date) AS latest_game, MIN(date) AS oldest_game
        FROM head_to_head
    """)
    row = c.fetchone()
    print(f"total_games: {row['total_games']}  latest: {row['latest_game']}  oldest: {row['oldest_game']}")

    print()
    print("=" * 60)
    print("2. head_to_head by sport")
    print("=" * 60)
    c.execute("""
        SELECT sport, COUNT(*) AS games, MAX(date) AS latest_game
        FROM head_to_head
        GROUP BY sport
        ORDER BY latest_game DESC
    """)
    h2h_by_sport = {r["sport"]: r for r in c.fetchall()}
    for sport, r in h2h_by_sport.items():
        print(f"  {sport:<10} {r['games']:>6} games   latest: {r['latest_game']}")

    print()
    print("=" * 60)
    print("3. results by sport (comparison — the live-pipeline table)")
    print("=" * 60)
    c.execute("""
        SELECT sport, COUNT(*) AS games, MAX(date) AS latest_result
        FROM results
        GROUP BY sport
        ORDER BY latest_result DESC
    """)
    results_by_sport = {r["sport"]: r for r in c.fetchall()}
    for sport, r in results_by_sport.items():
        print(f"  {sport:<10} {r['games']:>6} games   latest: {r['latest_result']}")

    conn.close()

    print()
    print("=" * 60)
    print("SUMMARY — head_to_head vs results, by sport")
    print("=" * 60)
    all_sports = sorted(set(h2h_by_sport) | set(results_by_sport))
    for sport in all_sports:
        h = h2h_by_sport.get(sport)
        r = results_by_sport.get(sport)
        h_games = h["games"] if h else 0
        h_latest = h["latest_game"] if h else "—"
        r_games = r["games"] if r else 0
        r_latest = r["latest_result"] if r else "—"
        gap_flag = ""
        if r and (not h or h["latest_game"] != r["latest_result"]):
            gap_flag = "  <-- head_to_head is behind results"
        print(f"  {sport:<10} h2h: {h_games:>5} (latest {h_latest})   results: {r_games:>5} (latest {r_latest}){gap_flag}")

    print()
    print("If h2h game counts are far below results counts for the same")
    print("sport/period, that confirms the 1st/15th sampling gap, not just")
    print("staleness — repoint elo_ratings.py's backfill at `results` rather")
    print("than trying to keep head_to_head current.")


if __name__ == "__main__":
    run()
