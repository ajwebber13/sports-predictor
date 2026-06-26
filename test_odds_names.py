from services.odds_parser import get_live_odds

games = get_live_odds("wnba")
for g in games:
    print(f"Home: '{g.get('home_team')}' | Away: '{g.get('away_team')}'")