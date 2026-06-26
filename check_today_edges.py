import requests

r = requests.get(
    "https://sports-predictor-api-44a0.onrender.com/wnba/edges",
    params={"simulations": 5000},
    timeout=60
)
data = r.json()
for bet in data.get("best_bets", []):
    print(f"{bet['game']} | model_prob: {bet['model_prob']} | edge: {round(bet.get('edge',0)*100,1)}%")