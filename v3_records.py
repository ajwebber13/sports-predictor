import sqlite3

conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

V3_START = "2026-06-19"

print("=" * 50)
print(f"V3 PERFORMANCE REPORT (since {V3_START})")
print("=" * 50)

# Overall
c.execute("""
    SELECT
        COUNT(*) as total,
        SUM(r.correct) as wins,
        ROUND(AVG(r.correct) * 100, 1) as win_pct
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE p.sport = 'wnba'
    AND r.date >= ?
    AND r.correct IS NOT NULL
""", (V3_START,))
row = c.fetchone()
losses = (row['total'] or 0) - (row['wins'] or 0)
print(f"Overall:   {row['wins']}-{losses} ({row['win_pct']}%)")

# Edge picks only (10%+)
c.execute("""
    SELECT
        COUNT(*) as total,
        SUM(r.correct) as wins,
        ROUND(AVG(r.correct) * 100, 1) as win_pct
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE p.sport = 'wnba'
    AND r.date >= ?
    AND r.correct IS NOT NULL
    AND p.edge >= 10
""", (V3_START,))
row = c.fetchone()
losses = (row['total'] or 0) - (row['wins'] or 0)
print(f"Edge picks (10%+): {row['wins']}-{losses} ({row['win_pct']}%)")

# By date
print("\n--- DAY BY DAY ---")
c.execute("""
    SELECT
        r.date,
        COUNT(*) as picks,
        SUM(r.correct) as wins
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE p.sport = 'wnba'
    AND r.date >= ?
    AND r.correct IS NOT NULL
    GROUP BY r.date
    ORDER BY r.date ASC
""", (V3_START,))
for row in c.fetchall():
    losses = row['picks'] - (row['wins'] or 0)
    print(f"  {row['date']}: {row['wins']}-{losses}")

conn.close()