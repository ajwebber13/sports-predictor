try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn, rows_to_dicts

conn = get_conn()
c = conn.cursor()
c.execute("""
    SELECT date, COUNT(*) as rows, COUNT(DISTINCT player_name) as players
    FROM cfb_game_log
    GROUP BY date
    ORDER BY date DESC
""")
rows = rows_to_dicts(c, c.fetchall())
if not rows:
    print("cfb_game_log is empty — nothing saved yet.")
else:
    for r in rows:
        print(r)
conn.close()
