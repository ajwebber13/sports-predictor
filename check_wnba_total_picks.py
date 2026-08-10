import json
from database import get_conn

conn = get_conn()
c = conn.cursor()
c.execute("""
    SELECT p.date, p.game, p.bet, p.odds, p.model_prob, p.implied_prob, p.edge,
           r.correct, r.home_score, r.away_score, r.home_team, r.away_team
    FROM predictions p
    JOIN results r ON r.prediction_id = p.id
    WHERE p.sport = 'wnba'
      AND p.market = 'total'
      AND r.correct IS NOT NULL
    ORDER BY p.date
""")
rows = c.fetchall()

print(f"Found {len(rows)} graded WNBA Total picks:\n")
for r in rows:
    total_score = (r["home_score"] or 0) + (r["away_score"] or 0)
    print(f"{r['date']}  {r['game']}")
    print(f"  Bet: {r['bet']} @ {r['odds']}")
    print(f"  model_prob={r['model_prob']}  implied_prob={r['implied_prob']}  edge={r['edge']}")
    print(f"  Final score: {r['home_team']} {r['home_score']} - {r['away_score']} {r['away_team']} "
          f"(total={total_score})")
    print(f"  Result: {'WIN' if r['correct'] == 1 else 'LOSS' if r['correct'] == 0 else 'PENDING'}")
    print()

# Also pull the matching prediction_factors rows if present, to check for
# the same total_line=0 / garbage-input class of bug seen elsewhere
print("\n--- Checking prediction_factors for these games ---")
c.execute("""
    SELECT pf.game_id, pf.home_team, pf.away_team, pf.home_score_final, pf.away_score_final
    FROM prediction_factors pf
    WHERE pf.sport = 'wnba'
    ORDER BY pf.created_at DESC
    LIMIT 30
""")
for r in c.fetchall():
    print(f"{r['game_id']}: {r['home_team']} {r['home_score_final']} - "
          f"{r['away_score_final']} {r['away_team']}")

conn.close()
