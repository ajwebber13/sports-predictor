from database import get_conn, rows_to_dicts

conn = get_conn()
c = conn.cursor()
c.execute("""
    SELECT COUNT(*) as total,
           SUM(CASE WHEN opponent IS NULL OR opponent = '' THEN 1 ELSE 0 END) as blank
    FROM player_props
    WHERE date = '2026-07-15' AND sport = 'wnba'
""")
print(rows_to_dicts(c, [c.fetchone()])[0])
conn.close()