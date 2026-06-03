"""
data/wnba_profiles.py
======================
EnhancedProfile objects for all 12 WNBA teams.
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


WNBA_PROFILES = {

    "Las Vegas Aces": EnhancedProfile(
        team_name="Las Vegas Aces", league="WNBA",
        pts_off=89.4, pts_def=78.2, ypp_off=1.08, ypp_def=0.94,
        to_given=12.4, to_forced=16.8, home_pts_off=92.0, away_pts_off=87.0,
        recent_off=91.0, recent_def=76.0, sos=0.72, injury_adj=0.0,
        advanced=adv(0.18, -0.16, 0.54, 0.36, 84, 0.22, 1820),
        history=hist(88.0, 78.0, 2.0, -1.0), ats=ats(22, 12),
    ),

    "New York Liberty": EnhancedProfile(
        team_name="New York Liberty", league="WNBA",
        pts_off=87.6, pts_def=79.4, ypp_off=1.06, ypp_def=0.96,
        to_given=11.8, to_forced=15.4, home_pts_off=90.0, away_pts_off=85.0,
        recent_off=89.0, recent_def=78.0, sos=0.70, injury_adj=0.0,
        advanced=adv(0.16, -0.14, 0.52, 0.37, 82, 0.21, 1800),
        history=hist(86.0, 79.0, 3.0, 0.0), ats=ats(20, 14),
    ),

    "Minnesota Lynx": EnhancedProfile(
        team_name="Minnesota Lynx", league="WNBA",
        pts_off=84.2, pts_def=80.6, ypp_off=1.02, ypp_def=0.97,
        to_given=12.2, to_forced=14.8, home_pts_off=87.0, away_pts_off=81.0,
        recent_off=85.0, recent_def=80.0, sos=0.68, injury_adj=0.0,
        advanced=adv(0.13, -0.12, 0.51, 0.38, 80, 0.20, 1770),
        history=hist(83.0, 80.0, 1.0, -1.0), ats=ats(18, 16),
    ),

    "Seattle Storm": EnhancedProfile(
        team_name="Seattle Storm", league="WNBA",
        pts_off=83.8, pts_def=81.4, ypp_off=1.01, ypp_def=0.98,
        to_given=12.6, to_forced=14.2, home_pts_off=86.0, away_pts_off=81.0,
        recent_off=84.0, recent_def=81.0, sos=0.67, injury_adj=0.0,
        advanced=adv(0.12, -0.11, 0.50, 0.39, 79, 0.19, 1750),
        history=hist(82.0, 81.0, 0.0, 0.0), ats=ats(17, 17),
    ),

    "Connecticut Sun": EnhancedProfile(
        team_name="Connecticut Sun", league="WNBA",
        pts_off=82.4, pts_def=80.2, ypp_off=1.00, ypp_def=0.97,
        to_given=11.6, to_forced=15.0, home_pts_off=85.0, away_pts_off=80.0,
        recent_off=83.0, recent_def=80.0, sos=0.69, injury_adj=0.0,
        advanced=adv(0.11, -0.13, 0.50, 0.38, 78, 0.21, 1740),
        history=hist(81.0, 80.0, 1.0, -1.0), ats=ats(18, 16),
    ),

    "Phoenix Mercury": EnhancedProfile(
        team_name="Phoenix Mercury", league="WNBA",
        pts_off=83.2, pts_def=83.8, ypp_off=1.01, ypp_def=1.01,
        to_given=13.4, to_forced=13.6, home_pts_off=86.0, away_pts_off=80.0,
        recent_off=84.0, recent_def=84.0, sos=0.65, injury_adj=0.0,
        advanced=adv(0.10, -0.08, 0.49, 0.40, 81, 0.18, 1700),
        history=hist(82.0, 83.0, 1.0, 1.0), ats=ats(16, 18),
    ),

    "Chicago Sky": EnhancedProfile(
        team_name="Chicago Sky", league="WNBA",
        pts_off=81.6, pts_def=84.2, ypp_off=0.99, ypp_def=1.02,
        to_given=13.8, to_forced=13.2, home_pts_off=84.0, away_pts_off=79.0,
        recent_off=82.0, recent_def=85.0, sos=0.64, injury_adj=0.0,
        advanced=adv(0.08, -0.06, 0.48, 0.41, 80, 0.18, 1670),
        history=hist(80.0, 84.0, 0.0, 2.0), ats=ats(15, 19),
    ),

    "Atlanta Dream": EnhancedProfile(
        team_name="Atlanta Dream", league="WNBA",
        pts_off=80.8, pts_def=84.6, ypp_off=0.98, ypp_def=1.02,
        to_given=14.2, to_forced=13.0, home_pts_off=83.0, away_pts_off=78.0,
        recent_off=81.0, recent_def=85.0, sos=0.63, injury_adj=0.0,
        advanced=adv(0.07, -0.05, 0.47, 0.41, 79, 0.17, 1650),
        history=hist(80.0, 84.0, 1.0, 1.0), ats=ats(14, 20),
    ),

    "Washington Mystics": EnhancedProfile(
        team_name="Washington Mystics", league="WNBA",
        pts_off=79.4, pts_def=86.2, ypp_off=0.96, ypp_def=1.04,
        to_given=14.6, to_forced=12.6, home_pts_off=82.0, away_pts_off=77.0,
        recent_off=79.0, recent_def=87.0, sos=0.62, injury_adj=-0.1,
        advanced=adv(0.05, -0.03, 0.46, 0.42, 78, 0.17, 1620),
        history=hist(79.0, 86.0, -1.0, 2.0), ats=ats(13, 21),
    ),

    "Indiana Fever": EnhancedProfile(
        team_name="Indiana Fever", league="WNBA",
        pts_off=82.8, pts_def=85.4, ypp_off=1.00, ypp_def=1.03,
        to_given=14.0, to_forced=13.4, home_pts_off=85.0, away_pts_off=80.0,
        recent_off=84.0, recent_def=85.0, sos=0.64, injury_adj=0.0,
        advanced=adv(0.09, -0.06, 0.48, 0.41, 82, 0.18, 1680),
        history=hist(81.0, 85.0, 3.0, 1.0), ats=ats(16, 18),
    ),

    "Dallas Wings": EnhancedProfile(
        team_name="Dallas Wings", league="WNBA",
        pts_off=78.6, pts_def=87.4, ypp_off=0.95, ypp_def=1.05,
        to_given=15.2, to_forced=12.2, home_pts_off=81.0, away_pts_off=76.0,
        recent_off=78.0, recent_def=88.0, sos=0.61, injury_adj=0.0,
        advanced=adv(0.03, -0.01, 0.45, 0.43, 77, 0.16, 1590),
        history=hist(78.0, 87.0, -1.0, 2.0), ats=ats(12, 22),
    ),

    "Golden State Valkyries": EnhancedProfile(
        team_name="Golden State Valkyries", league="WNBA",
        pts_off=80.2, pts_def=85.8, ypp_off=0.97, ypp_def=1.04,
        to_given=14.4, to_forced=12.8, home_pts_off=83.0, away_pts_off=77.0,
        recent_off=81.0, recent_def=86.0, sos=0.62, injury_adj=0.0,
        advanced=adv(0.06, -0.04, 0.47, 0.42, 80, 0.17, 1630),
        history=hist(79.0, 85.0, 2.0, 1.0), ats=ats(14, 20),
    ),

    "Los Angeles Sparks": EnhancedProfile(
        team_name="Los Angeles Sparks", league="CFB",
        pts_off=78.4, pts_def=84.2, ypp_off=0.95, ypp_def=1.02,
        to_given=14.8, to_forced=12.4, home_pts_off=81.0, away_pts_off=76.0,
        recent_off=78.0, recent_def=85.0, sos=0.61, injury_adj=0.0,
        advanced=adv(0.04, -0.02, 0.46, 0.42, 79, 0.17, 1610),
        history=hist(77.0, 84.0, -1.0, 1.0), ats=ats(13, 21),
    ),

    "Portland Fire": EnhancedProfile(
        team_name="Portland Fire", league="CFB",
        pts_off=76.8, pts_def=86.4, ypp_off=0.93, ypp_def=1.05,
        to_given=15.4, to_forced=12.0, home_pts_off=79.0, away_pts_off=75.0,
        recent_off=77.0, recent_def=87.0, sos=0.58, injury_adj=0.0,
        advanced=adv(0.02, -0.01, 0.44, 0.43, 78, 0.16, 1560),
        history=hist(76.0, 86.0, 0.0, 0.0), ats=ats(10, 14),
    ),

    "Toronto Tempo": EnhancedProfile(
        team_name="Toronto Tempo", league="CFB",
        pts_off=77.6, pts_def=85.8, ypp_off=0.94, ypp_def=1.04,
        to_given=15.2, to_forced=12.2, home_pts_off=80.0, away_pts_off=75.0,
        recent_off=78.0, recent_def=86.0, sos=0.59, injury_adj=0.0,
        advanced=adv(0.03, -0.01, 0.45, 0.43, 79, 0.16, 1570),
        history=hist(77.0, 85.0, 0.0, 0.0), ats=ats(11, 13),
    ),
}
