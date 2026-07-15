"""
check_todays_slate.py
Quick standalone check — runs today's real WNBA games through the
updated (injury-aware) predictor and prints projections side by side.
Does NOT post to Telegram, does NOT touch pick_of_the_day.py or the
alert pipeline — read-only eyeball check.

Still calls save_prediction_factors() under the hood (via predict()),
so today's real matchups will get logged into prediction_factors as
a side effect — that's fine/expected, same data either way.
"""

from wnba_data import get_team_stats
from wnba_predictor import WNBAPredictionEngine

# Today's slate (2026-07-15) — away @ home
GAMES = [
    ("Seattle Storm",         "Chicago Sky"),
    ("Los Angeles Sparks",    "Minnesota Lynx"),
    ("Golden State Valkyries","Indiana Fever"),
]

engine = WNBAPredictionEngine()

print(f"{'='*70}")
print("TODAY'S SLATE — injury-aware model")
print(f"{'='*70}\n")

for away_name, home_name in GAMES:
    home = get_team_stats(home_name)
    away = get_team_stats(away_name)

    if not home or not away:
        print(f"⚠️  Could not fetch stats for {away_name} @ {home_name} — skipping\n")
        continue

    pred = engine.predict(home, away, spread_line=0.0, over_under=164.0)

    fav = pred.home_team if pred.home_win_prob > pred.away_win_prob else pred.away_team
    fav_prob = max(pred.home_win_prob, pred.away_win_prob)

    print(f"{away_name} @ {home_name}")
    print(f"  Win Prob:   {home_name} {pred.home_win_prob}% | {away_name} {pred.away_win_prob}%")
    print(f"  Projected:  {pred.projected_home} - {pred.projected_away}")
    print(f"  --> Model favors: {fav} ({fav_prob}%)")
    print(f"  {home_name} factors: {pred.home_factors}")
    print(f"  {away_name} factors: {pred.away_factors}")
    print()