"""
debug_cfbd.py
=============
Diagnostic script — shows exactly what cfbd returns.
Run this to identify why defensive stats aren't loading.

Usage:
  python debug_cfbd.py
"""

import os
import cfbd

key = os.environ.get("CFBD_API_KEY", "")
if not key:
    key = input("Enter your CFBD API key: ").strip()

config = cfbd.Configuration()
config.api_key["Authorization"] = key
config.api_key_prefix["Authorization"] = "Bearer"
client = cfbd.ApiClient(config)

games_api = cfbd.GamesApi(client)
stats_api = cfbd.StatsApi(client)

print("\n" + "="*60)
print("TEST 1: Fetch all 2025 games (no filters)")
print("="*60)
try:
    games = games_api.get_games(year=2025)
    print(f"  Total games returned: {len(games)}")
    completed = [g for g in games if g.home_points is not None]
    print(f"  Completed games: {len(completed)}")
    if completed:
        g = completed[0]
        print(f"  Sample game: {g.away_team} @ {g.home_team}")
        print(f"  Score: {g.away_points} - {g.home_points}")
        print(f"  season_type: {getattr(g, 'season_type', 'N/A')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "="*60)
print("TEST 2: Fetch games filtered by team (Alabama)")
print("="*60)
try:
    games = games_api.get_games(year=2025, team="Alabama")
    completed = [g for g in games if g.home_points is not None]
    print(f"  Games found for Alabama: {len(completed)}")
    for g in completed[:3]:
        pts = g.home_points if g.home_team == "Alabama" else g.away_points
        opp_pts = g.away_points if g.home_team == "Alabama" else g.home_points
        opp = g.away_team if g.home_team == "Alabama" else g.home_team
        print(f"  Alabama {pts} - {opp} {opp_pts}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "="*60)
print("TEST 3: Fetch team season stats (all teams)")
print("="*60)
try:
    stats = stats_api.get_team_stats(year=2025)
    print(f"  Total stat records: {len(stats)}")
    alabama_stats = [s for s in stats if s.team == "Alabama"]
    print(f"  Alabama stat records: {len(alabama_stats)}")
    for s in alabama_stats[:8]:
        print(f"    {s.stat_name}: {s.stat_value}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "="*60)
print("TEST 4: Fetch team season stats (single team)")
print("="*60)
try:
    stats = stats_api.get_team_stats(year=2025, team="Alabama")
    print(f"  Records for Alabama: {len(stats)}")
    for s in stats[:10]:
        print(f"    {s.stat_name}: {s.stat_value}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "="*60)
print("TEST 5: Check Washington Huskies specifically")
print("="*60)
try:
    games = games_api.get_games(year=2025, team="Washington")
    completed = [g for g in games if g.home_points is not None]
    print(f"  Games found for Washington: {len(completed)}")
    for g in completed[:3]:
        pts = g.home_points if g.home_team == "Washington" else g.away_points
        opp_pts = g.away_points if g.home_team == "Washington" else g.home_points
        opp = g.away_team if g.home_team == "Washington" else g.home_team
        print(f"  Washington {pts} - {opp} {opp_pts}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\nDone. Paste this output so we can see what's happening.")
