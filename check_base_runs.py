import json
from database import get_conn

conn = get_conn()
c = conn.cursor()
c.execute("""
    SELECT pf.home_team, pf.away_team, pf.home_factors, pf.away_factors
    FROM prediction_factors pf
    WHERE pf.sport = 'mlb'
    ORDER BY pf.created_at DESC
    LIMIT 20
""")
rows = c.fetchall()
conn.close()

print(f"{'Home team':<25} {'Away team':<25} {'Home base_rpg':<15} {'Away base_rpg':<15}")
for r in rows:
    hf = r["home_factors"] if isinstance(r["home_factors"], dict) else json.loads(r["home_factors"])
    af = r["away_factors"] if isinstance(r["away_factors"], dict) else json.loads(r["away_factors"])
    h_base = hf.get("base_runs_per_game")
    a_base = af.get("base_runs_per_game")
    print(f"{r['home_team']:<25} {r['away_team']:<25} {str(h_base):<15} {str(a_base):<15}")
