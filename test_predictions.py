import requests

r = requests.get(
    "https://sports-predictor-api-44a0.onrender.com/wnba/predictions",
    params={"simulations": 5000},
    timeout=60
)
data = r.json()

print(f"Total predictions returned: {data.get('count', 0)}")
for bet in data.get("best_bets", []):
    print(f"  {bet['game']} — model_prob: {bet['model_prob']} | edge: {bet['edge']} | odds: {bet.get('odds', 'MISSING')}")