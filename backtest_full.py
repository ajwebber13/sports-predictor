import sqlite3

conn = sqlite3.connect("cp_analytics.db")
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=" * 50)
print("OVERALL WNBA BACKTEST")
print("=" * 50)

c.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(r.correct) as wins,
        ROUND(AVG(r.correct) * 100, 1) as win_pct,
        ROUND(SUM(
            CASE 
                WHEN r.correct = 1 THEN
                    CASE WHEN r.odds_at_pick < 0
                        THEN 100.0 / ABS(r.odds_at_pick)
                        ELSE r.odds_at_pick / 100.0
                    END
                ELSE -1.0
            END
        ) / COUNT(*) * 100, 1) as roi
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE p.sport = 'wnba'
    AND r.actual_winner IS NOT NULL
""")
row = c.fetchone()
print(f"Total picks:  {row['total']}")
print(f"Wins:         {row['wins']}")
print(f"Win rate:     {row['win_pct']}%")
print(f"ROI:          {row['roi']}%")

print("\n" + "=" * 50)
print("HOME vs AWAY PICK BREAKDOWN")
print("=" * 50)

c.execute("""
    SELECT
        CASE WHEN p.predicted_winner = p.home_team THEN 'Home' ELSE 'Away' END as pick_side,
        COUNT(*) as total,
        SUM(r.correct) as wins,
        ROUND(AVG(r.correct) * 100, 1) as win_pct,
        ROUND(SUM(
            CASE 
                WHEN r.correct = 1 THEN
                    CASE WHEN r.odds_at_pick < 0
                        THEN 100.0 / ABS(r.odds_at_pick)
                        ELSE r.odds_at_pick / 100.0
                    END
                ELSE -1.0
            END
        ) / COUNT(*) * 100, 1) as roi
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE p.sport = 'wnba'
    AND r.actual_winner IS NOT NULL
    GROUP BY pick_side
""")
for row in c.fetchall():
    print(f"\n{row['pick_side']} picks:")
    print(f"  Total:    {row['total']}")
    print(f"  Wins:     {row['wins']}")
    print(f"  Win rate: {row['win_pct']}%")
    print(f"  ROI:      {row['roi']}%")

print("\n" + "=" * 50)
print("EDGE TIER BREAKDOWN")
print("=" * 50)

c.execute("""
    SELECT
        CASE 
            WHEN p.edge >= 0.15 THEN '15%+ edge'
            WHEN p.edge >= 0.10 THEN '10-15% edge'
            WHEN p.edge >= 0.05 THEN '5-10% edge'
            ELSE 'Under 5%'
        END as tier,
        COUNT(*) as total,
        SUM(r.correct) as wins,
        ROUND(AVG(r.correct) * 100, 1) as win_pct,
        ROUND(SUM(
            CASE 
                WHEN r.correct = 1 THEN
                    CASE WHEN r.odds_at_pick < 0
                        THEN 100.0 / ABS(r.odds_at_pick)
                        ELSE r.odds_at_pick / 100.0
                    END
                ELSE -1.0
            END
        ) / COUNT(*) * 100, 1) as roi
    FROM results r
    JOIN predictions p ON r.prediction_id = p.id
    WHERE p.sport = 'wnba'
    AND r.actual_winner IS NOT NULL
    GROUP BY tier
    ORDER BY MIN(p.edge) DESC
""")
for row in c.fetchall():
    print(f"\n{row['tier']}:")
    print(f"  Total:    {row['total']}")
    print(f"  Wins:     {row['wins']}")
    print(f"  Win rate: {row['win_pct']}%")
    print(f"  ROI:      {row['roi']}%")

conn.close()