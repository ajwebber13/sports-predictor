"""
active_sports.py — Culture & Pulse Analytics
=============================================
ONE place that says which sports are live. Every alert path (game
picks, player props, Pick of the Day) reads this list. Shelving a
sport here shelves it everywhere — no more ghost posts from a
workflow that kept its own hardcoded list.

Rule (2026-09-03): no sport goes back in without an eyeballed
preflight of a real day's output.
"""

ALL_SPORTS = ["wnba", "nfl", "cfb"]  # game picks — nba, ncaab, mlb shelved

# Player-prop alerts are gated separately: a sport can have live game
# picks and shelved props (or vice versa). MLB props shelved 2026-09-04
# (props model lost at every threshold); WNBA props live on the
# projection-based selector only.
PROPS_SPORTS = ["wnba"]

# Power-rankings/preview content (2026-09-11): NOT odds-driven picks —
# no betting lines exist for these, so there's no edge/confidence gate
# to clear, unlike ALL_SPORTS/PROPS_SPORTS. hbcu_predict.py outputs
# pure model win probabilities + team strength as game previews, not
# bets. A separate list rather than folding into ALL_SPORTS because
# the whole rest of the pipeline (edge_finder, alert_throttle,
# game_pick_selector's MIN_EDGE_PCT) assumes "active" means "eligible
# to clear an edge threshold and get bet on" — HBCU never will.
# Empty until hbcu_predict.py's output has actually been eyeballed —
# see project notes. Not wired into render_job.py or any workflow yet;
# adding a sport key here does not, by itself, cause anything to run
# or send.
PREVIEW_SPORTS = []


def is_active(sport: str) -> bool:
    return (sport or "").lower() in ALL_SPORTS


def props_active(sport: str) -> bool:
    return (sport or "").lower() in PROPS_SPORTS


def preview_active(sport: str) -> bool:
    return (sport or "").lower() in PREVIEW_SPORTS
