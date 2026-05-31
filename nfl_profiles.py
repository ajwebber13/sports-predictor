"""
data/nfl_profiles.py
=====================
EnhancedProfile objects for all 32 NFL teams.
Stats based on 2025 season.
"""

from enhanced_data import EnhancedProfile, AdvancedMetrics, MultiYearProfile, ATSRecord


def adv(epa_off, epa_def, success_off, success_def, pace, havoc, elo):
    return AdvancedMetrics(
        epa_off=epa_off, epa_def=epa_def,
        success_rate_off=success_off, success_rate_def=success_def,
        pace=pace, explosiveness=1.0, havoc=havoc, elo=elo, sp_rating=0.0,
    )

def hist(w_pts_off, w_pts_def, trend_off, trend_def):
    return MultiYearProfile(
        weighted_pts_off=w_pts_off, weighted_pts_def=w_pts_def,
        weighted_epa_off=0.0, weighted_epa_def=0.0,
        trend_off=trend_off, trend_def=trend_def, years_available=3,
    )

def ats(w, l):
    pct = round(w / max(w + l, 1), 3)
    return ATSRecord(
        overall_w=w, overall_l=l, overall_p=0, overall_pct=pct,
        home_w=0, home_l=0, home_pct=0.0,
        away_w=0, away_l=0, away_pct=0.0,
        ou_over_w=0, ou_under_w=0, ou_pct=0.0, games_rated=w+l,
    )


NFL_PROFILES = {

    # AFC EAST
    "Buffalo Bills": EnhancedProfile(
        team_name="Buffalo Bills", league="NFL",
        pts_off=28.4, pts_def=18.2, ypp_off=6.2, ypp_def=4.9,
        to_given=1.1, to_forced=1.8, home_pts_off=30.0, away_pts_off=27.0,
        recent_off=29.0, recent_def=17.0, sos=0.52, injury_adj=0.0,
        advanced=adv(0.18, -0.14, 0.52, 0.37, 66, 0.21, 1680),
        history=hist(27.0, 19.0, 2.0, -1.0), ats=ats(9, 7),
    ),
    "Miami Dolphins": EnhancedProfile(
        team_name="Miami Dolphins", league="NFL",
        pts_off=25.8, pts_def=22.4, ypp_off=6.0, ypp_def=5.4,
        to_given=1.3, to_forced=1.6, home_pts_off=27.0, away_pts_off=24.0,
        recent_off=26.0, recent_def=22.0, sos=0.51, injury_adj=-0.1,
        advanced=adv(0.12, -0.07, 0.48, 0.41, 67, 0.18, 1580),
        history=hist(25.5, 22.0, 0.0, 1.0), ats=ats(7, 9),
    ),
    "New England Patriots": EnhancedProfile(
        team_name="New England Patriots", league="NFL",
        pts_off=19.8, pts_def=26.2, ypp_off=5.0, ypp_def=6.0,
        to_given=1.9, to_forced=1.3, home_pts_off=21.0, away_pts_off=18.0,
        recent_off=20.0, recent_def=27.0, sos=0.48, injury_adj=0.0,
        advanced=adv(0.01, 0.02, 0.41, 0.45, 60, 0.17, 1470),
        history=hist(20.0, 25.5, -3.0, 3.0), ats=ats(5, 11),
    ),
    "New York Jets": EnhancedProfile(
        team_name="New York Jets", league="NFL",
        pts_off=20.8, pts_def=25.2, ypp_off=5.2, ypp_def=5.8,
        to_given=1.7, to_forced=1.4, home_pts_off=22.0, away_pts_off=19.0,
        recent_off=21.0, recent_def=26.0, sos=0.50, injury_adj=0.0,
        advanced=adv(0.03, -0.02, 0.42, 0.44, 62, 0.17, 1495),
        history=hist(21.0, 25.0, 0.0, 1.0), ats=ats(6, 10),
    ),

    # AFC NORTH
    "Baltimore Ravens": EnhancedProfile(
        team_name="Baltimore Ravens", league="NFL",
        pts_off=27.8, pts_def=19.4, ypp_off=6.0, ypp_def=5.1,
        to_given=1.2, to_forced=1.9, home_pts_off=29.0, away_pts_off=26.0,
        recent_off=28.0, recent_def=19.0, sos=0.51, injury_adj=0.0,
        advanced=adv(0.16, -0.12, 0.50, 0.38, 64, 0.22, 1660),
        history=hist(26.5, 20.0, 1.0, 0.0), ats=ats(9, 7),
    ),
    "Cincinnati Bengals": EnhancedProfile(
        team_name="Cincinnati Bengals", league="NFL",
        pts_off=25.2, pts_def=23.4, ypp_off=6.0, ypp_def=5.6,
        to_given=1.5, to_forced=1.5, home_pts_off=27.0, away_pts_off=23.0,
        recent_off=26.0, recent_def=23.0, sos=0.50, injury_adj=-0.1,
        advanced=adv(0.12, -0.05, 0.48, 0.42, 66, 0.17, 1580),
        history=hist(25.5, 23.0, -2.0, 2.0), ats=ats(7, 9),
    ),
    "Cleveland Browns": EnhancedProfile(
        team_name="Cleveland Browns", league="NFL",
        pts_off=20.2, pts_def=24.4, ypp_off=5.1, ypp_def=5.7,
        to_given=1.8, to_forced=1.4, home_pts_off=22.0, away_pts_off=19.0,
        recent_off=20.0, recent_def=25.0, sos=0.50, injury_adj=-0.1,
        advanced=adv(0.02, -0.03, 0.42, 0.43, 61, 0.18, 1490),
        history=hist(20.5, 24.5, -2.0, 1.0), ats=ats(6, 10),
    ),
    "Pittsburgh Steelers": EnhancedProfile(
        team_name="Pittsburgh Steelers", league="NFL",
        pts_off=22.4, pts_def=19.8, ypp_off=5.4, ypp_def=5.1,
        to_given=1.3, to_forced=2.1, home_pts_off=24.0, away_pts_off=21.0,
        recent_off=22.0, recent_def=20.0, sos=0.50, injury_adj=0.0,
        advanced=adv(0.06, -0.10, 0.44, 0.39, 61, 0.23, 1590),
        history=hist(22.0, 20.5, -1.0, 0.0), ats=ats(8, 8),
    ),

    # AFC SOUTH
    "Houston Texans": EnhancedProfile(
        team_name="Houston Texans", league="NFL",
        pts_off=25.6, pts_def=21.4, ypp_off=5.8, ypp_def=5.4,
        to_given=1.4, to_forced=1.7, home_pts_off=27.0, away_pts_off=24.0,
        recent_off=26.0, recent_def=21.0, sos=0.50, injury_adj=0.0,
        advanced=adv(0.11, -0.08, 0.47, 0.41, 64, 0.19, 1610),
        history=hist(24.5, 22.0, 2.0, 1.0), ats=ats(8, 8),
    ),
    "Indianapolis Colts": EnhancedProfile(
        team_name="Indianapolis Colts", league="NFL",
        pts_off=22.8, pts_def=23.6, ypp_off=5.5, ypp_def=5.6,
        to_given=1.6, to_forced=1.5, home_pts_off=24.0, away_pts_off=21.0,
        recent_off=23.0, recent_def=24.0, sos=0.49, injury_adj=0.0,
        advanced=adv(0.07, -0.05, 0.44, 0.42, 62, 0.18, 1540),
        history=hist(22.5, 23.5, 0.0, 1.0), ats=ats(7, 9),
    ),
    "Jacksonville Jaguars": EnhancedProfile(
        team_name="Jacksonville Jaguars", league="NFL",
        pts_off=21.4, pts_def=25.6, ypp_off=5.3, ypp_def=5.9,
        to_given=1.7, to_forced=1.4, home_pts_off=23.0, away_pts_off=20.0,
        recent_off=21.0, recent_def=26.0, sos=0.49, injury_adj=0.0,
        advanced=adv(0.04, -0.02, 0.43, 0.44, 62, 0.17, 1510),
        history=hist(21.5, 25.0, -2.0, 2.0), ats=ats(6, 10),
    ),
    "Tennessee Titans": EnhancedProfile(
        team_name="Tennessee Titans", league="NFL",
        pts_off=19.2, pts_def=26.8, ypp_off=4.9, ypp_def=6.0,
        to_given=1.9, to_forced=1.3, home_pts_off=21.0, away_pts_off=18.0,
        recent_off=19.0, recent_def=27.0, sos=0.47, injury_adj=0.0,
        advanced=adv(0.00, 0.03, 0.41, 0.45, 61, 0.16, 1460),
        history=hist(19.5, 26.5, -2.0, 2.0), ats=ats(5, 11),
    ),

    # AFC WEST
    "Denver Broncos": EnhancedProfile(
        team_name="Denver Broncos", league="NFL",
        pts_off=23.2, pts_def=21.8, ypp_off=5.5, ypp_def=5.3,
        to_given=1.5, to_forced=1.6, home_pts_off=25.0, away_pts_off=21.0,
        recent_off=24.0, recent_def=22.0, sos=0.51, injury_adj=0.0,
        advanced=adv(0.08, -0.08, 0.45, 0.40, 62, 0.19, 1555),
        history=hist(23.0, 22.0, 1.0, 0.0), ats=ats(7, 9),
    ),
    "Kansas City Chiefs": EnhancedProfile(
        team_name="Kansas City Chiefs", league="NFL",
        pts_off=26.8, pts_def=18.8, ypp_off=5.9, ypp_def=4.8,
        to_given=1.2, to_forced=2.0, home_pts_off=28.0, away_pts_off=25.0,
        recent_off=27.0, recent_def=18.0, sos=0.52, injury_adj=0.0,
        advanced=adv(0.14, -0.13, 0.49, 0.37, 62, 0.20, 1700),
        history=hist(27.0, 18.5, 0.0, -1.0), ats=ats(8, 8),
    ),
    "Las Vegas Raiders": EnhancedProfile(
        team_name="Las Vegas Raiders", league="NFL",
        pts_off=20.6, pts_def=26.4, ypp_off=5.1, ypp_def=6.0,
        to_given=1.8, to_forced=1.3, home_pts_off=22.0, away_pts_off=19.0,
        recent_off=21.0, recent_def=27.0, sos=0.49, injury_adj=0.0,
        advanced=adv(0.02, 0.03, 0.42, 0.45, 62, 0.16, 1480),
        history=hist(21.0, 26.0, -1.0, 2.0), ats=ats(6, 10),
    ),
    "Los Angeles Chargers": EnhancedProfile(
        team_name="Los Angeles Chargers", league="NFL",
        pts_off=24.6, pts_def=22.2, ypp_off=5.8, ypp_def=5.4,
        to_given=1.4, to_forced=1.7, home_pts_off=26.0, away_pts_off=23.0,
        recent_off=25.0, recent_def=22.0, sos=0.51, injury_adj=0.0,
        advanced=adv(0.10, -0.08, 0.47, 0.41, 64, 0.19, 1595),
        history=hist(24.0, 22.5, 1.0, 0.0), ats=ats(7, 9),
    ),

    # NFC EAST
    "Dallas Cowboys": EnhancedProfile(
        team_name="Dallas Cowboys", league="NFL",
        pts_off=24.4, pts_def=23.8, ypp_off=5.7, ypp_def=5.6,
        to_given=1.5, to_forced=1.6, home_pts_off=26.0, away_pts_off=23.0,
        recent_off=24.0, recent_def=24.0, sos=0.50, injury_adj=0.0,
        advanced=adv(0.09, -0.06, 0.46, 0.42, 63, 0.18, 1565),
        history=hist(24.5, 23.5, -1.0, 1.0), ats=ats(7, 9),
    ),
    "New York Giants": EnhancedProfile(
        team_name="New York Giants", league="NFL",
        pts_off=19.4, pts_def=26.6, ypp_off=4.9, ypp_def=6.0,
        to_given=1.9, to_forced=1.3, home_pts_off=21.0, away_pts_off=18.0,
        recent_off=20.0, recent_def=27.0, sos=0.49, injury_adj=0.0,
        advanced=adv(0.01, 0.02, 0.41, 0.45, 61, 0.17, 1465),
        history=hist(19.5, 26.5, -2.0, 2.0), ats=ats(5, 11),
    ),
    "Philadelphia Eagles": EnhancedProfile(
        team_name="Philadelphia Eagles", league="NFL",
        pts_off=27.4, pts_def=19.6, ypp_off=6.1, ypp_def=5.0,
        to_given=1.1, to_forced=1.9, home_pts_off=29.0, away_pts_off=26.0,
        recent_off=28.0, recent_def=19.0, sos=0.51, injury_adj=0.0,
        advanced=adv(0.15, -0.11, 0.51, 0.38, 65, 0.21, 1650),
        history=hist(26.5, 20.0, 1.0, -1.0), ats=ats(9, 7),
    ),
    "Washington Commanders": EnhancedProfile(
        team_name="Washington Commanders", league="NFL",
        pts_off=26.2, pts_def=22.4, ypp_off=5.9, ypp_def=5.4,
        to_given=1.3, to_forced=1.7, home_pts_off=28.0, away_pts_off=24.0,
        recent_off=27.0, recent_def=22.0, sos=0.50, injury_adj=0.0,
        advanced=adv(0.13, -0.09, 0.49, 0.40, 65, 0.19, 1620),
        history=hist(25.5, 22.5, 3.0, 1.0), ats=ats(8, 8),
    ),

    # NFC NORTH
    "Chicago Bears": EnhancedProfile(
        team_name="Chicago Bears", league="NFL",
        pts_off=20.4, pts_def=25.8, ypp_off=5.2, ypp_def=5.9,
        to_given=1.8, to_forced=1.4, home_pts_off=22.0, away_pts_off=19.0,
        recent_off=21.0, recent_def=26.0, sos=0.49, injury_adj=0.0,
        advanced=adv(0.03, -0.01, 0.42, 0.44, 62, 0.17, 1500),
        history=hist(20.5, 25.5, 1.0, 2.0), ats=ats(6, 10),
    ),
    "Detroit Lions": EnhancedProfile(
        team_name="Detroit Lions", league="NFL",
        pts_off=30.2, pts_def=20.1, ypp_off=6.4, ypp_def=5.2,
        to_given=1.0, to_forced=1.8, home_pts_off=32.0, away_pts_off=28.0,
        recent_off=31.0, recent_def=19.0, sos=0.49, injury_adj=0.0,
        advanced=adv(0.20, -0.10, 0.53, 0.39, 67, 0.19, 1670),
        history=hist(28.0, 21.0, 4.0, 1.0), ats=ats(10, 6),
    ),
    "Green Bay Packers": EnhancedProfile(
        team_name="Green Bay Packers", league="NFL",
        pts_off=25.4, pts_def=21.6, ypp_off=5.8, ypp_def=5.3,
        to_given=1.3, to_forced=1.7, home_pts_off=27.0, away_pts_off=24.0,
        recent_off=26.0, recent_def=21.0, sos=0.50, injury_adj=0.0,
        advanced=adv(0.11, -0.09, 0.48, 0.40, 63, 0.19, 1605),
        history=hist(25.0, 21.5, 1.0, 0.0), ats=ats(8, 8),
    ),
    "Minnesota Vikings": EnhancedProfile(
        team_name="Minnesota Vikings", league="NFL",
        pts_off=26.6, pts_def=22.8, ypp_off=6.0, ypp_def=5.5,
        to_given=1.4, to_forced=1.6, home_pts_off=28.0, away_pts_off=25.0,
        recent_off=27.0, recent_def=23.0, sos=0.50, injury_adj=0.0,
        advanced=adv(0.13, -0.08, 0.49, 0.41, 65, 0.18, 1615),
        history=hist(26.0, 22.5, 2.0, 1.0), ats=ats(8, 8),
    ),

    # NFC SOUTH
    "Atlanta Falcons": EnhancedProfile(
        team_name="Atlanta Falcons", league="NFL",
        pts_off=23.6, pts_def=24.2, ypp_off=5.6, ypp_def=5.7,
        to_given=1.5, to_forced=1.5, home_pts_off=25.0, away_pts_off=22.0,
        recent_off=24.0, recent_def=24.0, sos=0.48, injury_adj=0.0,
        advanced=adv(0.08, -0.04, 0.45, 0.42, 64, 0.18, 1560),
        history=hist(23.0, 24.5, 1.0, 2.0), ats=ats(7, 9),
    ),
    "Carolina Panthers": EnhancedProfile(
        team_name="Carolina Panthers", league="NFL",
        pts_off=18.6, pts_def=27.4, ypp_off=4.9, ypp_def=6.1,
        to_given=2.0, to_forced=1.2, home_pts_off=20.0, away_pts_off=17.0,
        recent_off=19.0, recent_def=28.0, sos=0.47, injury_adj=0.0,
        advanced=adv(-0.02, 0.04, 0.40, 0.46, 60, 0.16, 1450),
        history=hist(19.0, 27.0, -2.0, 3.0), ats=ats(5, 11),
    ),
    "New Orleans Saints": EnhancedProfile(
        team_name="New Orleans Saints", league="NFL",
        pts_off=21.8, pts_def=24.6, ypp_off=5.3, ypp_def=5.7,
        to_given=1.6, to_forced=1.5, home_pts_off=23.0, away_pts_off=20.0,
        recent_off=22.0, recent_def=25.0, sos=0.48, injury_adj=0.0,
        advanced=adv(0.05, -0.04, 0.43, 0.43, 63, 0.18, 1520),
        history=hist(22.0, 24.5, -1.0, 1.0), ats=ats(7, 9),
    ),
    "Tampa Bay Buccaneers": EnhancedProfile(
        team_name="Tampa Bay Buccaneers", league="NFL",
        pts_off=24.2, pts_def=23.0, ypp_off=5.7, ypp_def=5.5,
        to_given=1.3, to_forced=1.7, home_pts_off=26.0, away_pts_off=22.0,
        recent_off=24.0, recent_def=23.0, sos=0.48, injury_adj=0.0,
        advanced=adv(0.09, -0.07, 0.46, 0.41, 64, 0.19, 1570),
        history=hist(24.0, 23.0, 0.0, 0.0), ats=ats(8, 8),
    ),

    # NFC WEST
    "Arizona Cardinals": EnhancedProfile(
        team_name="Arizona Cardinals", league="NFL",
        pts_off=21.2, pts_def=26.0, ypp_off=5.2, ypp_def=5.9,
        to_given=1.8, to_forced=1.3, home_pts_off=23.0, away_pts_off=20.0,
        recent_off=21.0, recent_def=26.0, sos=0.49, injury_adj=0.0,
        advanced=adv(0.03, 0.02, 0.42, 0.44, 63, 0.17, 1505),
        history=hist(21.5, 25.5, 1.0, 1.0), ats=ats(6, 10),
    ),
    "Los Angeles Rams": EnhancedProfile(
        team_name="Los Angeles Rams", league="NFL",
        pts_off=24.8, pts_def=22.6, ypp_off=5.8, ypp_def=5.5,
        to_given=1.4, to_forced=1.6, home_pts_off=26.0, away_pts_off=23.0,
        recent_off=25.0, recent_def=22.0, sos=0.53, injury_adj=0.0,
        advanced=adv(0.10, -0.07, 0.47, 0.41, 65, 0.18, 1600),
        history=hist(24.0, 22.5, 0.0, 2.0), ats=ats(7, 9),
    ),
    "San Francisco 49ers": EnhancedProfile(
        team_name="San Francisco 49ers", league="NFL",
        pts_off=26.2, pts_def=20.8, ypp_off=5.9, ypp_def=5.3,
        to_given=1.3, to_forced=1.7, home_pts_off=28.0, away_pts_off=24.0,
        recent_off=25.0, recent_def=21.0, sos=0.53, injury_adj=-0.1,
        advanced=adv(0.13, -0.09, 0.48, 0.40, 63, 0.20, 1640),
        history=hist(26.0, 20.5, -1.0, 1.0), ats=ats(8, 8),
    ),
    "Seattle Seahawks": EnhancedProfile(
        team_name="Seattle Seahawks", league="NFL",
        pts_off=23.4, pts_def=24.8, ypp_off=5.5, ypp_def=5.7,
        to_given=1.4, to_forced=1.6, home_pts_off=25.0, away_pts_off=22.0,
        recent_off=23.0, recent_def=25.0, sos=0.51, injury_adj=0.0,
        advanced=adv(0.08, -0.04, 0.45, 0.43, 63, 0.19, 1550),
        history=hist(23.5, 24.0, -1.0, 2.0), ats=ats(7, 9),
    ),
}
