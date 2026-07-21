try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn, rows_to_dicts

conn = get_conn()
c = conn.cursor()
c.execute("""
    SELECT date,
           COUNT(*) as total,
           SUM(CASE WHEN opponent IS NULL OR opponent = '' THEN 1 ELSE 0 END) as blank
    FROM player_props
    WHERE sport = 'wnba'
    GROUP BY date
    ORDER BY date DESC
""")
for row in rows_to_dicts(c, c.fetchall()):
    print(row)
conn.close()