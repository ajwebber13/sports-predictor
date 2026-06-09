import requests
from intel_feed import ODDS_API_KEY

for sport_key, label in [("basketball_nba", "NBA"), ("basketball_wnba", "WNBA")]:
    r = requests.get(
        f'https://api.the-odds-api.com/v4/sports/{sport_key}/odds',
        params={
            'apiKey': ODDS_API_KEY,
            'regions': 'us',
            'markets': 'h2h',
            'oddsFormat': 'american'
        }
    )
    data = r.json()
    print(f"\n{label} — Status: {r.status_code} | Games: {len(data)}")
    for game in data:
        print(f"  {game.get('away_team')} @ {game.get('home_team')} — {game.get('commence_time')}")
        for book in game.get('bookmakers', [])[:1]:
            for market in book.get('markets', []):
                for outcome in market.get('outcomes', []):
                    print(f"    {outcome['name']}: {outcome['price']:+d}")
