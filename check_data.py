from database import get_conn

conn = get_conn()
c = conn.cursor()

print("=== predictions by sport/market ===")
c.execute("SELECT sport, market, COUNT(*) FROM predictions GROUP BY sport, market ORDER BY sport, market")
for row in c.fetchall():
    print(row)

print("\n=== results by sport (joined) ===")
c.execute("""
    SELECT p.sport, p.market, COUNT(*)
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE r.correct IS NOT NULL
    GROUP BY p.sport, p.market
    ORDER BY p.sport, p.market
""")
for row in c.fetchall():
    print(row)

conn.close()