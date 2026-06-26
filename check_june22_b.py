import sqlite3
conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("--- PREDICTIONS ---")
c.execute("SELECT id, date, game, bet, predicted_winner, odds FROM predictions WHERE date = '2026-06-22' AND sport = 'wnba'")
for row in c.fetchall():
    print(dict(row))

print("\n--- RESULTS ---")
c.execute("SELECT date, game, actual_winner, correct, prediction_id FROM results WHERE date = '2026-06-22' AND sport = 'wnba'")
for row in c.fetchall():
    print(dict(row))

conn.close()