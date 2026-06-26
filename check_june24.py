import sqlite3
conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("--- PREDICTIONS (June 24) ---")
c.execute("""
    SELECT id, game, bet, predicted_winner, odds, edge
    FROM predictions
    WHERE date = '2026-06-24' AND sport = 'wnba'
""")
rows = c.fetchall()
if rows:
    for row in rows:
        print(dict(row))
else:
    print("No predictions found for June 24")

print("\n--- RESULTS (June 23) ---")
c.execute("""
    SELECT date, game, actual_winner, correct, prediction_id
    FROM results
    WHERE date = '2026-06-23' AND sport = 'wnba'
""")
rows = c.fetchall()
if rows:
    for row in rows:
        print(dict(row))
else:
    print("No results found for June 23")

conn.close()