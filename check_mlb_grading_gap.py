"""
check_mlb_grading_gap.py — Culture & Pulse Analytics
One-off diagnostic: MLB predictions were last GRADED on 2026-07-12,
four days before this check, despite MLB season being active. This
checks whether predictions are still being LOGGED at all (pipeline
alive, scoring broken) or logging itself stopped (pipeline dead) —
two very different problems with different fixes.
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

print("-- Recent MLB predictions logged (last 10, any grading status) --")
c.execute("""
    SELECT date, game, bet, model_prob
    FROM predictions
    WHERE sport = 'mlb'
    ORDER BY date DESC
    LIMIT 10
""")
for row in c.fetchall():
    print(dict(zip(["date", "game", "bet", "model_prob"], row)))

print("\n-- Recent MLB results (graded outcomes, last 10) --")
c.execute("""
    SELECT date, game, correct
    FROM results
    WHERE sport = 'mlb'
    ORDER BY date DESC
    LIMIT 10
""")
for row in c.fetchall():
    print(dict(zip(["date", "game", "correct"], row)))

conn.close()
