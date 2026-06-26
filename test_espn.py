import requests, pytz
from datetime import datetime

ct = pytz.timezone("America/Chicago")
today = datetime.now(ct).strftime("%Y%m%d")
r = requests.get(f"http://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={today}")
data = r.json()

for event in data.get("events", []):
    comps = event.get("competitions", [{}])[0]
    competitors = comps.get("competitors", [])
    home = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), "")
    away = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), "")
    status = event.get("status", {}).get("type", {}).get("name", "")
    print(f"{away} @ {home} — status: {status}")