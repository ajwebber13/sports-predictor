"""
sample_teams.py
================
Example team stat profiles for NFL and CFB.
Replace with real, current stats pulled from ESPN or an API.

How to update:
  1. Pull season averages from ESPN Stats / Pro Football Reference / cfbstats.com
  2. Update each field — these are illustrative 2024-style values
  3. Adjust recent_pts_* to reflect last 3–5 games before the matchup
  4. Set sos based on opponent quality index (0.0–1.0)
  5. Set injury_adj: −0.10 to −0.20 if QB or top skill player is out
"""

from predictor import TeamStats

# ═══════════════════════════════════════════════════════
# NFL TEAMS
# ═══════════════════════════════════════════════════════

KC_CHIEFS = TeamStats(
    name="Kansas City Chiefs",  league="NFL",
    pts_per_game_off=28.2,  yards_per_play_off=6.3,
    pts_per_game_def=17.1,  yards_per_play_def=4.9,
    turnovers_given=0.9,    turnovers_forced=1.8,
    home_pts_avg=30.1,      away_pts_avg=26.5,
    recent_pts_scored=31.4, recent_pts_allowed=14.2,
    sos=0.55,               injury_adj=0.0,
)

BUFFALO_BILLS = TeamStats(
    name="Buffalo Bills",       league="NFL",
    pts_per_game_off=26.8,  yards_per_play_off=6.1,
    pts_per_game_def=19.3,  yards_per_play_def=5.2,
    turnovers_given=1.1,    turnovers_forced=1.5,
    home_pts_avg=28.9,      away_pts_avg=24.7,
    recent_pts_scored=27.6, recent_pts_allowed=20.1,
    sos=0.52,               injury_adj=0.0,
)

BALTIMORE_RAVENS = TeamStats(
    name="Baltimore Ravens",    league="NFL",
    pts_per_game_off=30.1,  yards_per_play_off=6.6,
    pts_per_game_def=18.4,  yards_per_play_def=5.0,
    turnovers_given=1.0,    turnovers_forced=1.9,
    home_pts_avg=32.0,      away_pts_avg=28.2,
    recent_pts_scored=33.8, recent_pts_allowed=17.4,
    sos=0.53,               injury_adj=0.0,
)

DETROIT_LIONS = TeamStats(
    name="Detroit Lions",       league="NFL",
    pts_per_game_off=29.4,  yards_per_play_off=6.4,
    pts_per_game_def=20.6,  yards_per_play_def=5.3,
    turnovers_given=1.2,    turnovers_forced=1.3,
    home_pts_avg=31.5,      away_pts_avg=27.3,
    recent_pts_scored=30.8, recent_pts_allowed=22.0,
    sos=0.50,               injury_adj=0.0,
)

SF_49ERS = TeamStats(
    name="San Francisco 49ers", league="NFL",
    pts_per_game_off=24.7,  yards_per_play_off=6.0,
    pts_per_game_def=18.8,  yards_per_play_def=5.1,
    turnovers_given=1.3,    turnovers_forced=1.6,
    home_pts_avg=26.0,      away_pts_avg=23.4,
    recent_pts_scored=22.4, recent_pts_allowed=19.2,
    sos=0.54,               injury_adj=-0.08,   # injury concerns
)

DALLAS_COWBOYS = TeamStats(
    name="Dallas Cowboys",      league="NFL",
    pts_per_game_off=22.4,  yards_per_play_off=5.6,
    pts_per_game_def=22.8,  yards_per_play_def=5.5,
    turnovers_given=1.4,    turnovers_forced=1.2,
    home_pts_avg=24.2,      away_pts_avg=20.6,
    recent_pts_scored=19.8, recent_pts_allowed=25.4,
    sos=0.48,               injury_adj=0.0,
)

PHILADELPHIA_EAGLES = TeamStats(
    name="Philadelphia Eagles", league="NFL",
    pts_per_game_off=27.5,  yards_per_play_off=6.2,
    pts_per_game_def=19.2,  yards_per_play_def=5.0,
    turnovers_given=1.0,    turnovers_forced=1.7,
    home_pts_avg=29.3,      away_pts_avg=25.7,
    recent_pts_scored=28.6, recent_pts_allowed=18.8,
    sos=0.51,               injury_adj=0.0,
)

CHICAGO_BEARS = TeamStats(
    name="Chicago Bears",       league="NFL",
    pts_per_game_off=18.6,  yards_per_play_off=5.1,
    pts_per_game_def=24.3,  yards_per_play_def=5.7,
    turnovers_given=1.8,    turnovers_forced=1.1,
    home_pts_avg=20.1,      away_pts_avg=17.2,
    recent_pts_scored=17.4, recent_pts_allowed=26.8,
    sos=0.47,               injury_adj=0.0,
)


# ═══════════════════════════════════════════════════════
# COLLEGE FOOTBALL TEAMS
# (SOS matters far more here — update carefully)
# ═══════════════════════════════════════════════════════

OHIO_STATE = TeamStats(
    name="Ohio State Buckeyes", league="CFB",
    pts_per_game_off=41.3,  yards_per_play_off=7.6,
    pts_per_game_def=13.2,  yards_per_play_def=4.4,
    turnovers_given=1.0,    turnovers_forced=2.1,
    home_pts_avg=44.2,      away_pts_avg=38.5,
    recent_pts_scored=44.8, recent_pts_allowed=10.4,
    sos=0.78,               injury_adj=0.0,
)

GEORGIA_BULLDOGS = TeamStats(
    name="Georgia Bulldogs",    league="CFB",
    pts_per_game_off=38.7,  yards_per_play_off=7.2,
    pts_per_game_def=12.4,  yards_per_play_def=4.2,
    turnovers_given=0.9,    turnovers_forced=2.3,
    home_pts_avg=42.1,      away_pts_avg=35.4,
    recent_pts_scored=41.2, recent_pts_allowed=9.8,
    sos=0.75,               injury_adj=0.0,
)

TEXAS_LONGHORNS = TeamStats(
    name="Texas Longhorns",     league="CFB",
    pts_per_game_off=36.4,  yards_per_play_off=6.8,
    pts_per_game_def=17.6,  yards_per_play_def=5.0,
    turnovers_given=1.2,    turnovers_forced=1.8,
    home_pts_avg=40.2,      away_pts_avg=32.6,
    recent_pts_scored=38.4, recent_pts_allowed=16.2,
    sos=0.72,               injury_adj=0.0,
)

ALABAMA_CRIMSON_TIDE = TeamStats(
    name="Alabama Crimson Tide", league="CFB",
    pts_per_game_off=34.8,  yards_per_play_off=6.6,
    pts_per_game_def=16.2,  yards_per_play_def=4.8,
    turnovers_given=1.1,    turnovers_forced=2.0,
    home_pts_avg=38.5,      away_pts_avg=31.2,
    recent_pts_scored=33.6, recent_pts_allowed=18.8,
    sos=0.70,               injury_adj=0.0,
)

JACKSON_STATE_TIGERS = TeamStats(
    name="Jackson State Tigers",  league="CFB",
    pts_per_game_off=32.1,  yards_per_play_off=6.4,
    pts_per_game_def=19.3,  yards_per_play_def=5.1,
    turnovers_given=1.3,    turnovers_forced=1.7,
    home_pts_avg=35.4,      away_pts_avg=28.8,
    recent_pts_scored=34.2, recent_pts_allowed=17.6,
    sos=0.42,               injury_adj=0.0,
)

HOWARD_BISON = TeamStats(
    name="Howard Bison",          league="CFB",
    pts_per_game_off=24.6,  yards_per_play_off=5.7,
    pts_per_game_def=26.8,  yards_per_play_def=5.8,
    turnovers_given=1.7,    turnovers_forced=1.3,
    home_pts_avg=27.4,      away_pts_avg=21.8,
    recent_pts_scored=26.2, recent_pts_allowed=28.4,
    sos=0.38,               injury_adj=0.0,
)

PRAIRIE_VIEW_AM = TeamStats(
    name="Prairie View A&M",     league="CFB",
    pts_per_game_off=28.4,  yards_per_play_off=6.0,
    pts_per_game_def=22.6,  yards_per_play_def=5.4,
    turnovers_given=1.5,    turnovers_forced=1.6,
    home_pts_avg=31.2,      away_pts_avg=25.6,
    recent_pts_scored=30.8, recent_pts_allowed=20.4,
    sos=0.40,               injury_adj=0.0,
)
