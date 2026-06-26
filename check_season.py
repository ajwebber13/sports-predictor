from telegram_alerts import is_in_season

for sport in ["nba", "wnba", "nfl", "ncaaf", "ncaab"]:
    print(f"{sport.upper()}: {is_in_season(sport)}")