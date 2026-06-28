import sqlite3
conn = sqlite3.connect('cp_analytics.db')

for table in ['prop_results', 'wnba_game_log']:
    result = conn.execute(f"SELECT sql FROM sqlite_master WHERE name='{table}'").fetchone()
    print(f"\n--- {table} ---")
    print(result[0] if result else "Table not found")

conn.close()