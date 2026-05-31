CFB_CONSTANTS = {
    "league_avg_pts": 29.0, "league_avg_ypp": 5.9,
    "league_avg_to_given": 1.5, "home_adv_pts": 3.0, "score_std_dev": 10.5,
}
NFL_CONSTANTS = {
    "league_avg_pts": 23.0, "league_avg_ypp": 5.6,
    "league_avg_to_given": 1.2, "home_adv_pts": 2.5, "score_std_dev": 9.5,
}
def american_to_implied(odds):
    if odds > 0: return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)
def remove_vig(a, b):
    t = a + b
    if t == 0: return 0.5, 0.5
    return round(a / t * 100, 1), round(b / t * 100, 1)
