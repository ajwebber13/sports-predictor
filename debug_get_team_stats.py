import sys
sys.path.insert(0, ".")
from cfb_data import get_team_stats, _fetch_and_parse, FBS_TEAM_IDS

team_id = FBS_TEAM_IDS["Georgia"]

print("--- _fetch_and_parse, no season ---")
print(_fetch_and_parse("Georgia", team_id))

print("\n--- _fetch_and_parse, season=2025 ---")
print(_fetch_and_parse("Georgia", team_id, season=2025))

print("\n--- get_team_stats (full wrapper) ---")
print(get_team_stats("Georgia"))
