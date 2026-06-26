from wnba_data import get_team_stats
from wnba_predictor import WNBAPredictionEngine

home = "Seattle Storm"
away = "Dallas Wings"

home_stats = get_team_stats(home)
away_stats = get_team_stats(away)

print(f"\n{away}")
print(f"  Record: {away_stats.wins}-{away_stats.losses}")
print(f"  PPG: {away_stats.pts_per_game} | OPP PPG: {away_stats.opp_pts_per_game}")
print(f"  Off Rating: {away_stats.off_rating} | Def Rating: {away_stats.def_rating}")
print(f"  Net Rating: {away_stats.net_rating}")
print(f"  Away W/L: {away_stats.away_wins}-{away_stats.away_losses}")

print(f"\n{home}")
print(f"  Record: {home_stats.wins}-{home_stats.losses}")
print(f"  PPG: {home_stats.pts_per_game} | OPP PPG: {home_stats.opp_pts_per_game}")
print(f"  Off Rating: {home_stats.off_rating} | Def Rating: {home_stats.def_rating}")
print(f"  Net Rating: {home_stats.net_rating}")
print(f"  Home W/L: {home_stats.home_wins}-{home_stats.home_losses}")

engine = WNBAPredictionEngine()
pred = engine.predict(home_stats=home_stats, away_stats=away_stats, simulations=10000)

print(f"\nPrediction")
print(f"  Home win prob: {pred.home_win_prob}%")
print(f"  Away win prob: {pred.away_win_prob}%")
print(f"  Projected: {pred.projected_home}-{pred.projected_away}")