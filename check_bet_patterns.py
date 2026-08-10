import os
from database import get_conn

print("SUPABASE_DB_URL set:", bool(os.environ.get("SUPABASE_DB_URL")))

c = get_conn().cursor()
c.execute("""
    SELECT DISTINCT bet FROM predictions
    WHERE bet LIKE '%Over%' OR bet LIKE '%Under%'
       OR bet LIKE '%+%' OR bet LIKE '%-1%' OR bet LIKE '%-2%'
       OR bet LIKE '%-3%' OR bet LIKE '%-4%' OR bet LIKE '%-5%'
       OR bet LIKE '%-6%' OR bet LIKE '%-7%'
    LIMIT 30
""")
rows = c.fetchall()
print(f"\nFound {len(rows)} non-ML-looking bet values:")
for r in rows:
    print(r)
