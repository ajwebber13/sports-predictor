import sqlite3
conn = sqlite3.connect('cp_analytics.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("""
    SELECT sport, COUNT(*) as total
    FROM predictions
    GROUP BY sport
    ORDER BY total DESC
""")
rows = c.fetchall()
print("PREDICTIONS TABLE:")
for r in rows:
    print(f"  {r['sport'].upper()}: {r['total']} total")

c.execute("SELECT COUNT(*) as total FROM results WHERE correct IS NOT NULL")
print(f"\nRESULTS TABLE: {c.fetchone()['total']} scored picks")
conn.close()
