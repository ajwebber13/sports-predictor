import sqlite3
conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute("""
    SELECT date, game, actual_winner, correct, prediction_id
    FROM results
    WHERE sport = 'wnba'
    AND date >= '2026-06-19'
    ORDER BY date
""")
for row in c.fetchall():
    print(dict(row))
conn.close()