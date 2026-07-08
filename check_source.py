import sqlite3

conn = sqlite3.connect("cp_analytics.db")
c = conn.cursor()

print("Source breakdown for 2026-07-02:")
for row in c.execute("SELECT source, COUNT(*) FROM player_props WHERE date='2026-07-02' GROUP BY source"):
    print(" ", row)

print("\nAll rows (player, team, stat, source):")
for row in c.execute("SELECT player_name, team_name, stat, source FROM player_props WHERE date='2026-07-02' ORDER BY team_name, player_name"):
    print(" ", row)

conn.close()
