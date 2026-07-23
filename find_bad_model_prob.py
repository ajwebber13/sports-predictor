"""
find_bad_model_prob.py — one-off diagnostic
Finds the exact predictions where model_prob is >= 100% (impossible)
or otherwise out of the valid 0-100 range, so the root cause can be
traced by sport/game/date instead of guessing.

Usage:
    py find_bad_model_prob.py
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn

conn = get_conn()
c = conn.cursor()
c.execute("""
    SELECT p.id, p.sport, p.date, p.game, p.bet, p.model_prob, r.edge_at_pick, r.correct
    FROM predictions p
    LEFT JOIN results r ON r.prediction_id = p.id
    WHERE p.model_prob IS NOT NULL AND (p.model_prob >= 100 OR p.model_prob < 0)
    ORDER BY p.date DESC
""")
rows = c.fetchall()
conn.close()

if not rows:
    print("No out-of-range model_prob values found.")
else:
    print(f"Found {len(rows)} out-of-range prediction(s):\n")
    for r in rows:
        print(f"  id={r['id']}  {r['sport']}  {r['date']}  {r['game']}")
        print(f"    bet={r['bet']}  model_prob={r['model_prob']}  edge_at_pick={r['edge_at_pick']}  correct={r['correct']}")
        print()
