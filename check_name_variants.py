from database import get_conn

conn = get_conn()
c = conn.cursor()
c.execute("SELECT DISTINCT player_name FROM mlb_game_log WHERE player_name LIKE '%lcantara%' OR player_name LIKE '%lc%ntara%'")
rows = c.fetchall()
print("Matching names in mlb_game_log:")
for r in rows:
    print(" -", repr(r[0]))

c.execute("SELECT DISTINCT player_name FROM player_props WHERE player_name LIKE '%lcantara%' OR player_name LIKE '%lc%ntara%'")
rows2 = c.fetchall()
print("\nMatching names in player_props:")
for r in rows2:
    print(" -", repr(r[0]))

conn.close()
