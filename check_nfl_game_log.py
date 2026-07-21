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
    FROM nfl_game_log
    GROUP BY date
    ORDER BY date DESC
""")
rows = rows_to_dicts(c, c.fetchall())
if not rows:
    print("nfl_game_log is empty — nothing saved yet.")
else:
    total_rows = sum(r["rows"] for r in rows)
    print(f"Total: {total_rows} rows across {len(rows)} dates\n")
    for r in rows:
        print(r)
conn.close()
