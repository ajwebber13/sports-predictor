import sqlite3
conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT * FROM odds_history WHERE sport = 'wnba' ORDER BY captured_at DESC LIMIT 5")
rows = c.fetchall()
if rows:
    for row in rows:
        print(dict(row))
else:
    print("No WNBA odds in odds_history table")
conn.close()