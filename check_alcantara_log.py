from database import get_conn

conn = get_conn()
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM mlb_game_log WHERE player_name = 'Sandy Alcantara'")
print("Sandy Alcantara rows in mlb_game_log:", c.fetchone()[0])

c.execute("SELECT MIN(date), MAX(date) FROM mlb_game_log WHERE player_name = 'Sandy Alcantara'")
print("Date range:", c.fetchone())

conn.close()
