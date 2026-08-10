import requests
import json
from mlb_data import MLB_TEAM_IDS, ESPN_TEAM_STATS_URL

team_name = "New York Yankees"
team_id = MLB_TEAM_IDS.get(team_name)
url = ESPN_TEAM_STATS_URL.format(team_id=team_id)

resp = requests.get(url)
data = resp.json()

print("Top-level keys:", list(data.keys()))
print()

# Print structure (keys only, truncated) of each top-level section
def summarize(obj, prefix="", depth=0, max_depth=4):
    if depth > max_depth:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            print(f"{prefix}{k}: {type(v).__name__}" +
                  (f" (len={len(v)})" if isinstance(v, (list, dict)) else f" = {v}" if not isinstance(v, dict) else ""))
            summarize(v, prefix + "  ", depth + 1, max_depth)
    elif isinstance(obj, list) and obj:
        print(f"{prefix}[0]:")
        summarize(obj[0], prefix + "  ", depth + 1, max_depth)

summarize(data)

# Save full response to a file for closer inspection if needed
with open("espn_response_sample.json", "w") as f:
    json.dump(data, f, indent=2)
print("\nFull response saved to espn_response_sample.json")
