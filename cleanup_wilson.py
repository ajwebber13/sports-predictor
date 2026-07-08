import sqlite3
conn = sqlite3.connect("cp_analytics.db")
c = conn.cursor()
c.execute("DELETE FROM player_props WHERE date = ? AND player_name = ?", ("2026-06-30", "A'ja Wilson"))
conn.commit()
print(f"Deleted {c.rowcount} row(s)")
conn.close()
