from database import get_conn

conn = get_conn()
c = conn.cursor()

c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("TABLES:", tables)

for t in tables:
    c.execute(f"PRAGMA table_info({t})")
    cols = [(r[1], r[2]) for r in c.fetchall()]
    print(f"\n{t}:")
    for col in cols:
        print(f"  {col[0]} ({col[1]})")

conn.close()
from database import get_conn

conn = get_conn()
c = conn.cursor()

c.execute("""
    SELECT season, COUNT(*) as games
    FROM head_to_head
    WHERE sport = 'wnba'
    GROUP BY season
    ORDER BY season
""")
for r in c.fetchall():
    print(dict(r))

conn.close()