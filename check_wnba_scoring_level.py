from database import get_conn
from wnba_data import TEAM_IDS, get_team_stats

conn = get_conn()
c = conn.cursor()

print("--- advanced_metrics table check ---")
c.execute("""
    SELECT team_name, off_rating, def_rating, pace, season
    FROM advanced_metrics
    WHERE sport = 'wnba'
    ORDER BY team_name, season DESC
""")
rows = c.fetchall()
print(f"Found {len(rows)} rows total")
seen = set()
for r in rows:
    if r["team_name"] in seen:
        continue
    seen.add(r["team_name"])
    print(f"  {r['team_name']:<25} off={r['off_rating']}  def={r['def_rating']}  "
          f"pace={r['pace']}  season={r['season']}")
missing = set(TEAM_IDS.keys()) - seen
if missing:
    print(f"\n  Teams with NO advanced_metrics row at all: {sorted(missing)}")
conn.close()

print("\n--- Real current league scoring level (from get_team_stats) ---")
totals_scored = []
totals_allowed = []
for team in TEAM_IDS:
    stats = get_team_stats(team)
    if stats:
        print(f"  {team:<25} pts_per_game={stats.pts_per_game}  opp_pts_per_game={stats.opp_pts_per_game}")
        totals_scored.append(stats.pts_per_game)
        totals_allowed.append(stats.opp_pts_per_game)

if totals_scored:
    real_league_avg = sum(totals_scored) / len(totals_scored)
    print(f"\n  REAL current league average pts_per_game: {real_league_avg:.1f}")
    print(f"  Hardcoded LEAGUE_AVG_PPG constant in wnba_predictor.py: 82.0")
    print(f"  Difference: {real_league_avg - 82.0:+.1f}")
