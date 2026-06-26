import sqlite3
from datetime import datetime

conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Insert predictions manually
c.execute("""
    INSERT OR IGNORE INTO predictions
    (date, sport, game, home_team, away_team, bet, odds,
     model_prob, implied_prob, edge, home_record, away_record,
     home_rest, away_rest, predicted_winner)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    '2026-06-22', 'wnba', 'Toronto Tempo @ Atlanta Dream',
    'Atlanta Dream', 'Toronto Tempo',
    'Atlanta Dream ML', -204,
    69.5, 52.4, 17.1,
    '11-4', '8-8', 2, 3,
    'Atlanta Dream'
))

c.execute("""
    INSERT OR IGNORE INTO predictions
    (date, sport, game, home_team, away_team, bet, odds,
     model_prob, implied_prob, edge, home_record, away_record,
     home_rest, away_rest, predicted_winner)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (
    '2026-06-22', 'wnba', 'Dallas Wings @ Seattle Storm',
    'Seattle Storm', 'Dallas Wings',
    'Dallas Wings ML', -202,
    60.6, 23.8, 15.6,
    '3-14', '10-6', 2, 2,
    'Dallas Wings'
))

conn.commit()

# Now link results to predictions
c.execute("SELECT id FROM predictions WHERE date = '2026-06-22' AND game = 'Toronto Tempo @ Atlanta Dream' AND sport = 'wnba'")
row = c.fetchone()
if row:
    c.execute("UPDATE results SET prediction_id = ?, edge_at_pick = 17.1, odds_at_pick = -204 WHERE date = '2026-06-22' AND game = 'Toronto Tempo @ Atlanta Dream' AND sport = 'wnba'", (row['id'],))
    print(f"Linked Toronto/Atlanta — prediction id: {row['id']}")

c.execute("SELECT id FROM predictions WHERE date = '2026-06-22' AND game = 'Dallas Wings @ Seattle Storm' AND sport = 'wnba'")
row = c.fetchone()
if row:
    c.execute("UPDATE results SET prediction_id = ?, edge_at_pick = 15.6, odds_at_pick = -202 WHERE date = '2026-06-22' AND game = 'Dallas Wings @ Seattle Storm' AND sport = 'wnba'", (row['id'],))
    print(f"Linked Dallas/Seattle — prediction id: {row['id']}")

conn.commit()
conn.close()
print("Done.")