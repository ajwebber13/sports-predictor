import requests

r = requests.get(
    "https://sports-predictor-api-44a0.onrender.com/wnba/predictions",
    params={"simulations": 5000},
    timeout=60
)
data = r.json()

print(f"Total: {data.get('count')}")
for bet in data.get("best_bets", []):
    print(f"  {bet['game']} | implied: {bet['implied_prob']} | edge: {bet['edge']}")