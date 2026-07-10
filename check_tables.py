from database import get_conn

conn = get_conn()

rows = conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
).fetchall()

print("\nDATABASE TABLES")
print("=" * 40)

for row in rows:
    print(row[0])

conn.close()