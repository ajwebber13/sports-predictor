from enhanced_data import EnhancedProfile, AdvancedMetrics, MultiYearProfile, ATSRecord

def adv(epa_off, epa_def, success_off, success_def, pace, havoc, elo):
    return AdvancedMetrics(epa_off=epa_off, epa_def=epa_def, success_rate_off=success_off, success_rate_def=success_def, pace=pace, explosiveness=1.0, havoc=havoc, elo=elo, sp_rating=0.0)

def hist(w_pts_off, w_pts_def, trend_off, trend_def):
    return MultiYearProfile(weighted_pts_off=w_pts_off, weighted_pts_def=w_pts_def, weighted_epa_off=0.0, weighted_epa_def=0.0, trend_off=trend_off, trend_def=trend_def, years_available=3)

def ats(w, l):
    pct = round(w / max(w + l, 1), 3)
    return ATSRecord(overall_w=w, overall_l=l, overall_p=0, overall_pct=pct, home_w=0, home_l=0, home_pct=0.0, away_w=0, away_l=0, away_pct=0.0, ou_over_w=0, ou_under_w=0, ou_pct=0.0, games_rated=w+l)

TEAM_PROFILES = {
    "Ohio State": EnhancedProfile(team_name="Ohio State", league="CFB", pts_off=38.4, pts_def=17.2, ypp_off=6.8, ypp_def=4.6, to_given=1.1, to_forced=2.0, home_pts_off=41.0, away_pts_off=35.0, recent_off=39.0, recent_def=16.0, sos=0.72, injury_adj=0.0, advanced=adv(0.18,-0.14,0.50,0.36,73,0.22,1820), history=hist(36.0,18.0,3.0,-1.0), ats=ats(9,5)),
    "Oregon": EnhancedProfile(team_name="Oregon", league="CFB", pts_off=40.1, pts_def=19.5, ypp_off=7.1, ypp_def=4.9, to_given=0.9, to_forced=1.8, home_pts_off=43.0, away_pts_off=37.0, recent_off=41.0, recent_def=18.0, sos=0.68, injury_adj=0.0, advanced=adv(0.22,-0.11,0.52,0.38,76,0.20,1840), history=hist(37.5,20.0,5.0,0.0), ats=ats(10,5)),
    "Georgia": EnhancedProfile(team_name="Georgia", league="CFB", pts_off=33.8, pts_def=15.4, ypp_off=6.2, ypp_def=4.3, to_given=1.2, to_forced=2.1, home_pts_off=36.0, away_pts_off=31.0, recent_off=34.0, recent_def=15.0, sos=0.74, injury_adj=0.0, advanced=adv(0.12,-0.18,0.47,0.34,70,0.24,1790), history=hist(34.0,16.0,0.0,-2.0), ats=ats(8,6)),
    "Texas": EnhancedProfile(team_name="Texas", league="CFB", pts_off=35.2, pts_def=18.8, ypp_off=6.4, ypp_def=4.7, to_given=1.4, to_forced=1.7, home_pts_off=38.0, away_pts_off=32.0, recent_off=36.0, recent_def=18.0, sos=0.73, injury_adj=0.0, advanced=adv(0.14,-0.12,0.48,0.37,68,0.21,1775), history=hist(33.0,19.5,4.0,1.0), ats=ats(8,7)),
    "Alabama": EnhancedProfile(team_name="Alabama", league="CFB", pts_off=34.6, pts_def=22.1, ypp_off=6.3, ypp_def=5.1, to_given=1.5, to_forced=1.6, home_pts_off=37.0, away_pts_off=32.0, recent_off=33.0, recent_def=22.0, sos=0.76, injury_adj=-0.1, advanced=adv(0.13,-0.08,0.46,0.40,69,0.19,1750), history=hist(35.0,18.0,-2.0,2.0), ats=ats(7,7)),
    "Penn State": EnhancedProfile(team_name="Penn State", league="CFB", pts_off=32.4, pts_def=16.8, ypp_off=6.0, ypp_def=4.4, to_given=1.3, to_forced=1.9, home_pts_off=35.0, away_pts_off=29.0, recent_off=33.0, recent_def=16.0, sos=0.69, injury_adj=0.0, advanced=adv(0.10,-0.15,0.46,0.35,67,0.23,1760), history=hist(31.0,17.5,1.0,-1.0), ats=ats(7,6)),
    "Notre Dame": EnhancedProfile(team_name="Notre Dame", league="CFB", pts_off=36.1, pts_def=18.0, ypp_off=6.5, ypp_def=4.5, to_given=1.2, to_forced=1.8, home_pts_off=39.0, away_pts_off=33.0, recent_off=37.0, recent_def=17.0, sos=0.67, injury_adj=0.0, advanced=adv(0.15,-0.13,0.49,0.36,71,0.21,1780), history=hist(33.5,18.5,2.0,-1.0), ats=ats(9,5)),
    "LSU": EnhancedProfile(team_name="LSU", league="CFB", pts_off=37.8, pts_def=23.4, ypp_off=6.7, ypp_def=5.3, to_given=1.6, to_forced=1.5, home_pts_off=41.0, away_pts_off=34.0, recent_off=38.0, recent_def=23.0, sos=0.71, injury_adj=0.0, advanced=adv(0.17,-0.06,0.50,0.41,74,0.18,1740), history=hist(36.0,22.0,1.0,3.0), ats=ats(8,6)),
    "Clemson": EnhancedProfile(team_name="Clemson", league="CFB", pts_off=31.5, pts_def=17.6, ypp_off=5.9, ypp_def=4.5, to_given=1.3, to_forced=1.7, home_pts_off=34.0, away_pts_off=29.0, recent_off=32.0, recent_def=17.0, sos=0.64, injury_adj=0.0, advanced=adv(0.09,-0.14,0.45,0.36,66,0.22,1730), history=hist(30.0,18.0,0.0,-1.0), ats=ats(7,7)),
    "Oklahoma": EnhancedProfile(team_name="Oklahoma", league="CFB", pts_off=33.2, pts_def=21.8, ypp_off=6.1, ypp_def=5.0, to_given=1.4, to_forced=1.6, home_pts_off=36.0, away_pts_off=30.0, recent_off=33.0, recent_def=21.0, sos=0.65, injury_adj=0.0, advanced=adv(0.11,-0.09,0.46,0.39,70,0.19,1710), history=hist(32.0,21.0,-1.0,1.0), ats=ats(6,8)),
}
