"""
check_team_integrity.py - Culture & Pulse Sports Analytics

Validates team-identity data integrity across predictions and results,
ahead of building Streak Finder / Power Rankings / Team Profile /
Matchup Analyzer, which all depend on clean home_team/away_team values.

Read-only. Safe to run any time. No confirmation gate needed.
"""

from database import get_conn


def run():
    conn = get_conn()
    c = conn.cursor()

    print("=" * 60)
    print("1. Blank/NULL team fields")
    print("=" * 60)

    c.execute("""
        SELECT COUNT(*) FROM predictions
        WHERE home_team IS NULL OR home_team = ''
           OR away_team IS NULL OR away_team = ''
    """)
    pred_blank = c.fetchone()[0]
    print(f"predictions with blank home/away_team: {pred_blank}")

    c.execute("""
        SELECT COUNT(*) FROM results
        WHERE home_team IS NULL OR home_team = ''
           OR away_team IS NULL OR away_team = ''
    """)
    res_blank = c.fetchone()[0]
    print(f"results with blank home/away_team: {res_blank}")

    print()
    print("=" * 60)
    print("2. Malformed game strings (missing ' @ ')")
    print("=" * 60)

    c.execute("""
        SELECT game FROM predictions
        WHERE game NOT LIKE '%@%'
        LIMIT 25
    """)
    malformed = c.fetchall()
    if malformed:
        for row in malformed:
            print(f"  {row['game']}")
    else:
        print("  none found")

    print()
    print("=" * 60)
    print("3. game vs home_team/away_team consistency spot check")
    print("=" * 60)

    c.execute("""
        SELECT game, home_team, away_team FROM predictions
        LIMIT 25
    """)
    rows = c.fetchall()
    flipped = 0
    for row in rows:
        game, home, away = row["game"], row["home_team"], row["away_team"]
        parts = game.split(" @ ")
        expected_away = parts[0].strip() if len(parts) == 2 else None
        expected_home = parts[1].strip() if len(parts) == 2 else None
        flag = ""
        if expected_home and expected_away:
            if home != expected_home or away != expected_away:
                flag = "  <-- MISMATCH/FLIPPED"
                flipped += 1
        print(f"  {game:<35} home={home!r:<20} away={away!r:<20}{flag}")

    print()
    print(f"Mismatches in this 25-row sample: {flipped}")

    print()
    print("=" * 60)
    print("4. Distinct team-name spellings (canonical-name check)")
    print("=" * 60)

    c.execute("""
        SELECT DISTINCT home_team AS team FROM predictions WHERE home_team != ''
        UNION
        SELECT DISTINCT away_team AS team FROM predictions WHERE away_team != ''
        ORDER BY team
    """)
    teams = [r["team"] for r in c.fetchall()]
    print(f"Total distinct team-name strings across predictions: {len(teams)}")
    print("Full list (scan for near-duplicates like 'LA Lakers' vs 'Los Angeles Lakers'):")
    for t in teams:
        print(f"  {t}")

    conn.close()

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"predictions blank team fields: {pred_blank}")
    print(f"results blank team fields:     {res_blank}")
    print(f"malformed game strings found:  {len(malformed)}")
    print(f"distinct team-name strings:    {len(teams)}")
    if pred_blank == 0 and res_blank == 0 and not malformed:
        print("-> Team identity structurally clean. Proceed with dynamic queries.")
    else:
        print("-> Fix required before Streak Finder / Power Rankings / Team Profile.")


if __name__ == "__main__":
    run()
