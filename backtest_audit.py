import sqlite3

conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Check what tables exist
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("Tables:", tables)

# Check picks table structure
for table in tables:
    print(f"\n--- {table} ---")
    c.execute(f"PRAGMA table_info({table})")
    for col in c.fetchall():
        print(f"  {col['name']} ({col['type']})")

conn.close()