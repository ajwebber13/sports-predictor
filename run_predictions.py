"""
run_predictions.py
==================
Example matchups demonstrating the prediction engine.

How to run:
  python run_predictions.py

To add your own matchup:
  1. Import or define two TeamStats objects
  2. Create a MatchupInput with Vegas lines and odds
  3. Call engine.predict(matchup) and print_prediction(result)

Where to get Vegas lines:
  - DraftKings / FanDuel / ESPN BET
  - The Action Network (actionnetwork.com)
  - Covers.com
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from predictor import MatchupInput, PredictionEngine
from display import print_prediction, print_batch_summary, export_json
from sample_teams import (
    KC_CHIEFS, BUFFALO_BILLS, BALTIMORE_RAVENS, DETROIT_LIONS,
    PHILADELPHIA_EAGLES, DALLAS_COWBOYS,
    OHIO_STATE, GEORGIA_BULLDOGS, TEXAS_LONGHORNS, ALABAMA_CRIMSON_TIDE,
    JACKSON_STATE_TIGERS, HOWARD_BISON,
)

engine = PredictionEngine()


# ═══════════════════════════════════════════════════════════════
# NFL MATCHUP 1: Chiefs (home) vs Bills
# Vegas line: Chiefs -3.5  |  O/U 47.5
# Odds: Chiefs -185 / Bills +155
# ═══════════════════════════════════════════════════════════════

nfl_1 = MatchupInput(
    team_a          = KC_CHIEFS,
    team_b          = BUFFALO_BILLS,
    spread_line     = 3.5,        # KC favored by 3.5
    over_under_line = 47.5,
    team_a_odds     = -185,
    team_b_odds     = +155,
    neutral_site    = False,
    team_a_is_home  = True,
    simulations     = 10000,
)

# ═══════════════════════════════════════════════════════════════
# NFL MATCHUP 2: Ravens (away) vs Eagles (home)
# Vegas line: Eagles -2.5  |  O/U 50.0
# Odds: Eagles -135 / Ravens +115
# ═══════════════════════════════════════════════════════════════

nfl_2 = MatchupInput(
    team_a          = PHILADELPHIA_EAGLES,  # home
    team_b          = BALTIMORE_RAVENS,     # away
    spread_line     = 2.5,                  # Eagles favored by 2.5
    over_under_line = 50.0,
    team_a_odds     = -135,
    team_b_odds     = +115,
    neutral_site    = False,
    team_a_is_home  = True,
    simulations     = 10000,
)

# ═══════════════════════════════════════════════════════════════
# CFB MATCHUP 1: Georgia (home) vs Texas
# Playoff-style game. Vegas: Georgia -6.5  |  O/U 55.5
# Odds: Georgia -240 / Texas +195
# ═══════════════════════════════════════════════════════════════

cfb_1 = MatchupInput(
    team_a          = GEORGIA_BULLDOGS,
    team_b          = TEXAS_LONGHORNS,
    spread_line     = 6.5,
    over_under_line = 55.5,
    team_a_odds     = -240,
    team_b_odds     = +195,
    neutral_site    = False,
    team_a_is_home  = True,
    simulations     = 10000,
)

# ═══════════════════════════════════════════════════════════════
# CFB MATCHUP 2: HBCU — Jackson State (home) vs Howard
# Vegas: JSU -13.5  |  O/U 49.0
# Odds: JSU -550 / Howard +400
# ═══════════════════════════════════════════════════════════════

cfb_2 = MatchupInput(
    team_a          = JACKSON_STATE_TIGERS,
    team_b          = HOWARD_BISON,
    spread_line     = 13.5,
    over_under_line = 49.0,
    team_a_odds     = -550,
    team_b_odds     = +400,
    neutral_site    = False,
    team_a_is_home  = True,
    simulations     = 10000,
)


# ═══════════════════════════════════════════════════════════════
# RUN ALL PREDICTIONS
# ═══════════════════════════════════════════════════════════════

print("\n" + "━" * 62)
print("  SPORTS BETTING PREDICTION ENGINE  v1.0")
print("  NFL & College Football | Monte Carlo Probability Model")
print("━" * 62)
print("  ⚠  This is a probability model for analytical purposes.")
print("     All outputs are probabilistic estimates, not picks.")
print("━" * 62)

matchups = [nfl_1, nfl_2, cfb_1, cfb_2]
predictions = engine.batch_predict(matchups)

# Detailed reports
labels = ["NFL GAME 1", "NFL GAME 2", "CFB GAME 1", "CFB GAME 2"]
for label, pred in zip(labels, predictions):
    print(f"\n  ── {label} {'─' * (54 - len(label))}")
    print_prediction(pred)

# Batch summary table
print_batch_summary(predictions)

# JSON export (for frontend or storage)
export_json(predictions, "predictions_output.json")
