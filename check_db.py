import sqlite3
conn = sqlite3.connect('cp_analytics.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('Tables:', cursor.fetchall())
cursor.execute("PRAGMA table_info(player_props)")
print('player_props columns:')
for row in cursor.fetchall():
    print(' ', row)
conn.close()