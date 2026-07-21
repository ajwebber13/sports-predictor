try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn, rows_to_dicts

conn = get_conn()
c = conn.cursor()
c.execute("""
    SELECT p.id, p.date, p.sport, p.game, p.bet, p.model_prob
    FROM predictions p
    WHERE p.sport = 'mlb' AND p.date = '2026-07-17'
    ORDER BY p.id
""")
rows = rows_to_dicts(c, c.fetchall())
print(f"Found {len(rows)} MLB predictions for 2026-07-17:")
for r in rows:
    print(r)
conn.close()
