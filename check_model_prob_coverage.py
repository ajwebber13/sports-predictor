"""
check_model_prob_coverage.py — Culture & Pulse Analytics
One-off diagnostic: how many graded predictions actually have a real
model_prob value, by sport, and since when. Built to check the scope
of the model_prob data loss from the 2026-07-13 Turso incident
(rebuild_predictions.py could not reconstruct model_prob from results
alone) before deciding whether calibration_audit.py has enough data
to say anything yet.
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
    SELECT r.sport,
           COUNT(*) as total_graded,
           SUM(CASE WHEN p.model_prob IS NOT NULL THEN 1 ELSE 0 END) as has_model_prob,
           MIN(CASE WHEN p.model_prob IS NOT NULL THEN r.date END) as earliest_with_prob,
           MAX(r.date) as latest_graded
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE r.correct IS NOT NULL
    GROUP BY r.sport
    ORDER BY r.sport
""")
for row in c.fetchall():
    print(dict(zip(["sport", "total_graded", "has_model_prob", "earliest_with_prob", "latest_graded"], row)))
conn.close()
