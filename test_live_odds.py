from services.odds_parser import get_live_odds

games = get_live_odds("wnba")
print(f"Games returned: {len(games)}")
for g in games:
    home = g.get("home_team", "")
    away = g.get("away_team", "")
    for bm in g.get("bookmakers", [])[:1]:
        for market in bm.get("markets", []):
            if market["key"] == "h2h":
                for o in market.get("outcomes", []):
                    print(f"  {away} @ {home} — {o['name']}: {o['price']}")