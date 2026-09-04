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

ALL_SPORTS = ["wnba", "nfl", "cfb"]  # nba, ncaab, mlb shelved


def is_active(sport: str) -> bool:
    return (sport or "").lower() in ALL_SPORTS
