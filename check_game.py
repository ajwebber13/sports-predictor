"""
check_game.py — quick one-off check
Run: python check_game.py
"""
import sqlite3

conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT player_name, pts, reb, ast, game_type
    FROM wnba_game_log
    WHERE date = '20260630'
    ORDER BY pts DESC
""").fetchall()

print(f"{len(rows)} row(s) found for 2026-06-30\n")
for r in rows:
    print(f"  {r['player_name']:<22} {r['pts']:>4.0f} pts  {r['reb']:>4.0f} reb  {r['ast']:>4.0f} ast   [{r['game_type']}]")

conn.close()
