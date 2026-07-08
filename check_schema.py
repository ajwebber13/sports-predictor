import sqlite3
conn = sqlite3.connect('cp_analytics.db')

c = conn.cursor()
c.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(correct) as wins,
        SUM(CASE WHEN edge_at_pick >= 10 THEN 1 ELSE 0 END) as edge_total,
        SUM(CASE WHEN edge_at_pick >= 10 AND correct = 1 THEN 1 ELSE 0 END) as edge_wins
    FROM results
    WHERE sport = 'wnba'
""")
row = c.fetchone()
total      = row[0] or 0
wins       = row[1] or 0
edge_total = row[2] or 0
edge_wins  = row[3] or 0
losses     = total - wins
pct        = round(wins / total * 100, 1) if total > 0 else 0
print(f"Overall: {wins}-{losses} ({pct}%) — {total} picks")
print(f"Edge picks: {edge_wins}-{edge_total - edge_wins} — {edge_total} picks")
conn.close()