import sqlite3
conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("""
    SELECT p.date, p.game, p.bet, p.odds, r.correct
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE p.sport = 'wnba'
    ORDER BY p.date DESC
""")
for row in c.fetchall():
    print(f"{row['date']} | {row['game']} | {row['bet']} | odds: {row['odds']} | correct: {row['correct']}")
conn.close()