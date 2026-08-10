import requests
from mlb_data import MLB_TEAM_IDS, ESPN_TEAM_STATS_URL, _parse_stat_categories

team_name = "New York Yankees"
team_id = MLB_TEAM_IDS.get(team_name)
print(f"Team ID for {team_name}: {team_id}")

url = ESPN_TEAM_STATS_URL.format(team_id=team_id)
print(f"URL: {url}")

resp = requests.get(url)
print(f"Status code: {resp.status_code}")

if resp.status_code != 200:
    print("Non-200 response, body:")
    print(resp.text[:1000])
else:
    data = resp.json()
    categories = data.get("splits", [])
    print(f"Number of 'splits' found: {len(categories)}")
    if not categories:
        print("EMPTY splits list — this is why it falls back to flat defaults.")
        print("Top-level keys in response:", list(data.keys()))
    else:
        stats = _parse_stat_categories(categories)
        print("Parsed stats:", stats)
