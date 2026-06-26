import sqlite3
conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Fix predicted_winner in predictions
c.execute("""
    UPDATE predictions
    SET predicted_winner = 'Atlanta Dream'
    WHERE date = '2026-06-22' AND sport = 'wnba'
    AND game = 'Toronto Tempo @ Atlanta Dream'
""")

c.execute("""
    UPDATE predictions
    SET predicted_winner = 'Dallas Wings'
    WHERE date = '2026-06-22' AND sport = 'wnba'
    AND game = 'Dallas Wings @ Seattle Storm'
""")

# Fix results — Atlanta Dream and Dallas Wings both won
c.execute("""
    UPDATE results
    SET actual_winner = 'Atlanta Dream',
        correct = 1,
        prediction_id = (
            SELECT id FROM predictions
            WHERE date = '2026-06-22' AND sport = 'wnba'
            AND game = 'Toronto Tempo @ Atlanta Dream'
        )
    WHERE date = '2026-06-22' AND sport = 'wnba'
    AND game = 'Toronto Tempo @ Atlanta Dream'
""")

c.execute("""
    UPDATE results
    SET actual_winner = 'Dallas Wings',
        correct = 1,
        prediction_id = (
            SELECT id FROM predictions
            WHERE date = '2026-06-22' AND sport = 'wnba'
            AND game = 'Dallas Wings @ Seattle Storm'
        )
    WHERE date = '2026-06-22' AND sport = 'wnba'
    AND game = 'Dallas Wings @ Seattle Storm'
""")

conn.commit()
conn.close()
print("Fixed.")