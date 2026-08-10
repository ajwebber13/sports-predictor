from mlb_data import get_team_stats

teams = [
    "New York Yankees", "Boston Red Sox", "Los Angeles Dodgers",
    "Colorado Rockies", "Miami Marlins", "Houston Astros",
]

for team in teams:
    stats = get_team_stats(team)
    print(f"{team:<25} {stats}")
