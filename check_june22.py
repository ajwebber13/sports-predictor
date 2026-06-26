import sqlite3
conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("""
    SELECT date, sport, game, predicted_winner, bet, odds
    FROM predictions
    WHERE date = '2026-06-22' AND sport = 'wnba'
""")
rows = c.fetchall()
if rows:
    for row in rows:
        print(dict(row))
else:
    print("No WNBA predictions found for 2026-06-22")
conn.close()