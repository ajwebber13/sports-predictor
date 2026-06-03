"""
data/team_profiles.py
======================
EnhancedProfile objects for:
  - All AP Top 25 teams (2025 preseason)
  - Key HBCU programs (SWAC + MEAC)
  - Additional cupcake/opponent teams

Stats based on 2025 season averages.
Will be replaced by live cfb_data.py when season starts in August.
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

def profile(name, pts_off, pts_def, ypp_off, ypp_def, to_given, to_forced,
            epa_off, epa_def, success_off, success_def, pace, havoc, elo,
            sos=0.65, ats_w=8, ats_l=6):
    return EnhancedProfile(
        team_name    = name, league="CFB",
        pts_off      = pts_off, pts_def=pts_def,
        ypp_off      = ypp_off, ypp_def=ypp_def,
        to_given     = to_given, to_forced=to_forced,
        home_pts_off = round(pts_off * 1.05, 1),
        away_pts_off = round(pts_off * 0.95, 1),
        recent_off   = pts_off, recent_def=pts_def,
        sos=sos, injury_adj=0.0,
        advanced     = adv(epa_off, epa_def, success_off, success_def, pace, havoc, elo),
        history      = hist(pts_off, pts_def, 0.0, 0.0),
        ats          = ats(ats_w, ats_l),
    )


TEAM_PROFILES = {

    # ─── AP TOP 25 (2025 Preseason) ───────────────────────────

    # 1. Texas
    "Texas": profile("Texas", 35.2, 18.8, 6.4, 4.7, 1.4, 1.7,
                     0.14, -0.12, 0.48, 0.37, 68, 0.21, 1775, sos=0.73, ats_w=8, ats_l=7),

    # 2. Penn State
    "Penn State": profile("Penn State", 32.4, 16.8, 6.0, 4.4, 1.3, 1.9,
                          0.10, -0.15, 0.46, 0.35, 67, 0.23, 1760, sos=0.69, ats_w=7, ats_l=6),

    # 3. Ohio State
    "Ohio State": profile("Ohio State", 38.4, 17.2, 6.8, 4.6, 1.1, 2.0,
                          0.18, -0.14, 0.50, 0.36, 73, 0.22, 1820, sos=0.72, ats_w=9, ats_l=5),

    # 4. Clemson
    "Clemson": profile("Clemson", 31.5, 17.6, 5.9, 4.5, 1.3, 1.7,
                       0.09, -0.14, 0.45, 0.36, 66, 0.22, 1730, sos=0.64, ats_w=7, ats_l=7),

    # 5. Georgia
    "Georgia": profile("Georgia", 33.8, 15.4, 6.2, 4.3, 1.2, 2.1,
                       0.12, -0.18, 0.47, 0.34, 70, 0.24, 1790, sos=0.74, ats_w=8, ats_l=6),

    # 6. Notre Dame
    "Notre Dame": profile("Notre Dame", 36.1, 18.0, 6.5, 4.5, 1.2, 1.8,
                          0.15, -0.13, 0.49, 0.36, 71, 0.21, 1780, sos=0.67, ats_w=9, ats_l=5),

    # 7. Oregon
    "Oregon": profile("Oregon", 40.1, 19.5, 7.1, 4.9, 0.9, 1.8,
                      0.22, -0.11, 0.52, 0.38, 76, 0.20, 1840, sos=0.68, ats_w=10, ats_l=5),

    # 8. Alabama
    "Alabama": profile("Alabama", 34.6, 22.1, 6.3, 5.1, 1.5, 1.6,
                       0.13, -0.08, 0.46, 0.40, 69, 0.19, 1750, sos=0.76, ats_w=7, ats_l=7),

    # 9. LSU
    "LSU": profile("LSU", 37.8, 23.4, 6.7, 5.3, 1.6, 1.5,
                   0.17, -0.06, 0.50, 0.41, 74, 0.18, 1740, sos=0.71, ats_w=8, ats_l=6),

    # 10. Miami
    "Miami": profile("Miami", 34.2, 21.6, 6.3, 5.2, 1.4, 1.7,
                     0.13, -0.09, 0.47, 0.40, 70, 0.19, 1690, sos=0.65, ats_w=8, ats_l=6),

    # 11. Arizona State
    "Arizona State": profile("Arizona State", 33.8, 22.4, 6.2, 5.3, 1.5, 1.6,
                              0.12, -0.08, 0.47, 0.41, 72, 0.18, 1660, sos=0.63, ats_w=7, ats_l=7),

    # 12. Illinois
    "Illinois": profile("Illinois", 29.6, 20.2, 5.8, 5.0, 1.4, 1.8,
                        0.08, -0.10, 0.45, 0.39, 65, 0.20, 1620, sos=0.66, ats_w=7, ats_l=7),

    # 13. South Carolina
    "South Carolina": profile("South Carolina", 31.2, 22.8, 5.9, 5.4, 1.5, 1.6,
                               0.10, -0.07, 0.46, 0.41, 67, 0.18, 1610, sos=0.68, ats_w=7, ats_l=7),

    # 14. Michigan
    "Michigan": profile("Michigan", 30.8, 19.4, 5.8, 4.9, 1.3, 1.8,
                        0.09, -0.11, 0.46, 0.38, 64, 0.21, 1660, sos=0.67, ats_w=8, ats_l=6),

    # 15. Florida
    "Florida": profile("Florida", 30.4, 22.6, 5.9, 5.3, 1.5, 1.6,
                       0.09, -0.08, 0.46, 0.41, 68, 0.18, 1600, sos=0.67, ats_w=7, ats_l=7),

    # 16. SMU
    "SMU": profile("SMU", 33.6, 24.2, 6.2, 5.6, 1.5, 1.5,
                   0.12, -0.06, 0.47, 0.42, 72, 0.17, 1590, sos=0.62, ats_w=7, ats_l=7),

    # 17. Kansas State
    "Kansas State": profile("Kansas State", 31.8, 21.4, 6.0, 5.2, 1.4, 1.7,
                             0.10, -0.09, 0.47, 0.40, 66, 0.19, 1600, sos=0.64, ats_w=8, ats_l=6),

    # 18. Oklahoma
    "Oklahoma": profile("Oklahoma", 33.2, 21.8, 6.1, 5.0, 1.4, 1.6,
                        0.11, -0.09, 0.46, 0.39, 70, 0.19, 1710, sos=0.65, ats_w=6, ats_l=8),

    # 19. Texas A&M
    "Texas A&M": profile("Texas A&M", 32.4, 22.2, 6.0, 5.3, 1.4, 1.6,
                          0.11, -0.08, 0.46, 0.40, 67, 0.18, 1630, sos=0.69, ats_w=7, ats_l=7),

    # 20. Indiana
    "Indiana": profile("Indiana", 34.8, 24.6, 6.3, 5.7, 1.5, 1.5,
                       0.13, -0.06, 0.48, 0.42, 70, 0.17, 1610, sos=0.64, ats_w=8, ats_l=6),

    # 21. Ole Miss
    "Ole Miss": profile("Ole Miss", 35.4, 25.8, 6.4, 5.8, 1.6, 1.5,
                        0.14, -0.05, 0.48, 0.43, 73, 0.17, 1590, sos=0.66, ats_w=7, ats_l=7),

    # 22. Iowa State
    "Iowa State": profile("Iowa State", 30.2, 21.6, 5.8, 5.2, 1.4, 1.7,
                           0.09, -0.09, 0.46, 0.40, 65, 0.19, 1580, sos=0.63, ats_w=7, ats_l=7),

    # 23. Texas Tech
    "Texas Tech": profile("Texas Tech", 31.6, 23.4, 5.9, 5.5, 1.5, 1.5,
                           0.10, -0.07, 0.46, 0.42, 69, 0.17, 1560, sos=0.62, ats_w=7, ats_l=7),

    # 24. Tennessee
    "Tennessee": profile("Tennessee", 33.2, 22.8, 6.1, 5.4, 1.5, 1.6,
                          0.12, -0.08, 0.47, 0.41, 70, 0.18, 1610, sos=0.68, ats_w=7, ats_l=7),

    # 25. Boise State
    "Boise State": profile("Boise State", 33.8, 21.2, 6.2, 5.1, 1.3, 1.7,
                            0.12, -0.09, 0.48, 0.39, 71, 0.19, 1600, sos=0.58, ats_w=9, ats_l=5),

    # ─── OTHERS RECEIVING VOTES ───────────────────────────────

    "BYU": profile("BYU", 31.4, 22.6, 5.9, 5.4, 1.4, 1.6,
                   0.10, -0.08, 0.46, 0.40, 68, 0.18, 1570, sos=0.60, ats_w=8, ats_l=6),

    "Utah": profile("Utah", 29.8, 21.4, 5.7, 5.2, 1.4, 1.7,
                    0.08, -0.09, 0.45, 0.40, 65, 0.19, 1560, sos=0.61, ats_w=7, ats_l=7),

    "Baylor": profile("Baylor", 30.2, 23.6, 5.8, 5.5, 1.5, 1.5,
                      0.09, -0.07, 0.45, 0.42, 67, 0.17, 1540, sos=0.60, ats_w=7, ats_l=7),

    "Louisville": profile("Louisville", 32.4, 23.2, 6.0, 5.5, 1.4, 1.6,
                           0.11, -0.07, 0.47, 0.41, 68, 0.18, 1560, sos=0.62, ats_w=8, ats_l=6),

    "Missouri": profile("Missouri", 31.8, 23.8, 6.0, 5.6, 1.5, 1.5,
                        0.10, -0.06, 0.46, 0.42, 69, 0.17, 1540, sos=0.64, ats_w=7, ats_l=7),

    "Nebraska": profile("Nebraska", 28.6, 23.4, 5.6, 5.5, 1.5, 1.6,
                        0.07, -0.07, 0.44, 0.41, 64, 0.18, 1520, sos=0.62, ats_w=6, ats_l=8),

    "Georgia Tech": profile("Georgia Tech", 29.4, 24.6, 5.7, 5.7, 1.6, 1.5,
                             0.08, -0.06, 0.45, 0.42, 70, 0.17, 1510, sos=0.60, ats_w=7, ats_l=7),

    "Washington": profile("Washington", 30.2, 23.8, 5.8, 5.6, 1.5, 1.5,
                           0.09, -0.07, 0.46, 0.41, 67, 0.18, 1530, sos=0.61, ats_w=7, ats_l=7),

    "USC": profile("USC", 33.4, 26.2, 6.2, 5.9, 1.6, 1.4,
                   0.12, -0.05, 0.47, 0.43, 72, 0.16, 1560, sos=0.63, ats_w=7, ats_l=7),

    "Auburn": profile("Auburn", 28.8, 24.2, 5.6, 5.6, 1.6, 1.5,
                      0.07, -0.06, 0.44, 0.42, 66, 0.17, 1510, sos=0.67, ats_w=6, ats_l=8),

    "Arkansas": profile("Arkansas", 27.4, 24.8, 5.5, 5.7, 1.6, 1.5,
                        0.06, -0.06, 0.43, 0.42, 65, 0.17, 1490, sos=0.66, ats_w=6, ats_l=8),

    "Mississippi State": profile("Mississippi State", 25.6, 26.4, 5.3, 5.9, 1.7, 1.4,
                                  0.04, -0.04, 0.42, 0.43, 64, 0.16, 1460, sos=0.64, ats_w=6, ats_l=8),

    "Kentucky": profile("Kentucky", 27.8, 23.6, 5.5, 5.5, 1.5, 1.6,
                        0.06, -0.07, 0.44, 0.41, 63, 0.18, 1500, sos=0.65, ats_w=7, ats_l=7),

    "Vanderbilt": profile("Vanderbilt", 24.6, 27.8, 5.2, 6.0, 1.7, 1.4,
                           0.03, -0.02, 0.41, 0.44, 63, 0.16, 1440, sos=0.63, ats_w=6, ats_l=8),

    "Florida State": profile("Florida State", 28.4, 25.6, 5.6, 5.8, 1.6, 1.5,
                              0.07, -0.05, 0.44, 0.42, 66, 0.17, 1500, sos=0.62, ats_w=6, ats_l=8),

    "North Carolina": profile("North Carolina", 29.6, 26.4, 5.7, 5.9, 1.6, 1.5,
                               0.08, -0.05, 0.45, 0.42, 68, 0.16, 1490, sos=0.60, ats_w=7, ats_l=7),

    "Pittsburgh": profile("Pittsburgh", 28.2, 24.8, 5.5, 5.7, 1.5, 1.5,
                           0.07, -0.06, 0.44, 0.41, 65, 0.17, 1480, sos=0.59, ats_w=7, ats_l=7),

    "Colorado": profile("Colorado", 30.4, 27.6, 5.8, 6.0, 1.7, 1.4,
                        0.09, -0.04, 0.46, 0.43, 70, 0.16, 1510, sos=0.58, ats_w=7, ats_l=7),

    "UCF": profile("UCF", 29.8, 25.4, 5.7, 5.8, 1.5, 1.5,
                   0.08, -0.05, 0.45, 0.42, 69, 0.17, 1480, sos=0.57, ats_w=7, ats_l=7),

    "Cincinnati": profile("Cincinnati", 28.6, 24.2, 5.5, 5.6, 1.5, 1.6,
                           0.07, -0.07, 0.44, 0.41, 66, 0.18, 1470, sos=0.57, ats_w=7, ats_l=7),

    "Tulane": profile("Tulane", 30.2, 23.8, 5.8, 5.5, 1.4, 1.6,
                      0.09, -0.07, 0.46, 0.40, 68, 0.18, 1480, sos=0.55, ats_w=8, ats_l=6),

    "Army": profile("Army", 28.4, 22.6, 5.5, 5.3, 1.1, 1.7,
                    0.06, -0.08, 0.44, 0.40, 60, 0.19, 1460, sos=0.54, ats_w=8, ats_l=6),

    "Navy": profile("Navy", 26.8, 23.4, 5.3, 5.5, 1.2, 1.6,
                    0.05, -0.07, 0.43, 0.40, 58, 0.18, 1430, sos=0.52, ats_w=7, ats_l=7),

    # ─── HBCU PROGRAMS ────────────────────────────────────────

    # SWAC
    "Jackson State": profile("Jackson State", 28.4, 18.6, 5.4, 4.8, 1.5, 1.8,
                              0.06, -0.10, 0.44, 0.37, 67, 0.21, 1480, sos=0.40, ats_w=9, ats_l=5),

    "Grambling State": profile("Grambling State", 26.2, 20.4, 5.2, 5.0, 1.6, 1.7,
                                0.04, -0.08, 0.43, 0.38, 65, 0.20, 1440, sos=0.38, ats_w=8, ats_l=6),

    "Southern": profile("Southern", 24.8, 22.6, 5.0, 5.3, 1.7, 1.6,
                        0.03, -0.06, 0.42, 0.40, 64, 0.19, 1410, sos=0.37, ats_w=7, ats_l=7),

    "Prairie View A&M": profile("Prairie View A&M", 25.6, 21.8, 5.1, 5.2, 1.6, 1.6,
                                 0.04, -0.07, 0.42, 0.39, 65, 0.19, 1420, sos=0.38, ats_w=8, ats_l=6),

    "Florida A&M": profile("Florida A&M", 27.4, 20.2, 5.3, 5.0, 1.5, 1.7,
                            0.05, -0.08, 0.43, 0.38, 66, 0.20, 1450, sos=0.39, ats_w=8, ats_l=6),

    "Alabama A&M": profile("Alabama A&M", 24.2, 23.4, 5.0, 5.5, 1.7, 1.5,
                            0.03, -0.05, 0.41, 0.41, 63, 0.18, 1390, sos=0.37, ats_w=6, ats_l=8),

    "Alabama State": profile("Alabama State", 23.8, 24.2, 4.9, 5.6, 1.7, 1.5,
                              0.02, -0.05, 0.41, 0.41, 62, 0.17, 1380, sos=0.36, ats_w=6, ats_l=8),

    "Alcorn State": profile("Alcorn State", 22.4, 24.8, 4.8, 5.7, 1.8, 1.4,
                             0.01, -0.04, 0.40, 0.42, 62, 0.17, 1360, sos=0.35, ats_w=6, ats_l=8),

    "Texas Southern": profile("Texas Southern", 22.8, 25.4, 4.8, 5.8, 1.8, 1.4,
                               0.01, -0.03, 0.40, 0.43, 63, 0.16, 1350, sos=0.35, ats_w=5, ats_l=9),

    # MEAC
    "Howard": profile("Howard", 23.6, 24.6, 4.9, 5.6, 1.7, 1.5,
                      0.02, -0.05, 0.41, 0.41, 63, 0.17, 1370, sos=0.36, ats_w=6, ats_l=8),

    "North Carolina A&T": profile("North Carolina A&T", 24.4, 23.8, 5.0, 5.5, 1.6, 1.5,
                                   0.03, -0.06, 0.42, 0.41, 64, 0.18, 1390, sos=0.37, ats_w=7, ats_l=7),

    "Morgan State": profile("Morgan State", 21.8, 26.4, 4.7, 5.9, 1.9, 1.3,
                             0.00, -0.02, 0.39, 0.43, 61, 0.16, 1330, sos=0.34, ats_w=5, ats_l=9),

    "Hampton": profile("Hampton", 22.4, 25.6, 4.8, 5.8, 1.8, 1.4,
                       0.01, -0.03, 0.40, 0.42, 62, 0.17, 1340, sos=0.35, ats_w=5, ats_l=9),

    "South Carolina State": profile("South Carolina State", 24.8, 22.4, 5.0, 5.3, 1.6, 1.6,
                                     0.03, -0.06, 0.42, 0.40, 64, 0.18, 1400, sos=0.37, ats_w=7, ats_l=7),

    "Tennessee State": profile("Tennessee State", 23.2, 24.2, 4.9, 5.6, 1.7, 1.5,
                                0.02, -0.05, 0.41, 0.41, 63, 0.17, 1370, sos=0.36, ats_w=6, ats_l=8),

    "Bethune-Cookman": profile("Bethune-Cookman", 22.6, 25.2, 4.8, 5.7, 1.8, 1.4,
                                0.01, -0.04, 0.40, 0.42, 62, 0.17, 1350, sos=0.35, ats_w=5, ats_l=9),

    # ─── COMMON CUPCAKE / OPPONENT TEAMS ──────────────────────

    "Kennesaw State": profile("Kennesaw State", 24.6, 26.8, 5.0, 5.9, 1.7, 1.4,
                               0.03, -0.03, 0.41, 0.43, 65, 0.16, 1380, sos=0.45, ats_w=6, ats_l=8),

    "Sam Houston": profile("Sam Houston", 26.2, 24.4, 5.2, 5.6, 1.6, 1.5,
                            0.04, -0.05, 0.42, 0.41, 66, 0.17, 1400, sos=0.46, ats_w=7, ats_l=7),

    "UT Martin": profile("UT Martin", 18.4, 30.6, 4.4, 6.4, 2.0, 1.2,
                          -0.04, 0.06, 0.37, 0.47, 60, 0.14, 1250, sos=0.28, ats_w=4, ats_l=10),

    "Duquesne": profile("Duquesne", 17.8, 31.2, 4.3, 6.5, 2.1, 1.2,
                         -0.05, 0.07, 0.36, 0.47, 59, 0.14, 1230, sos=0.27, ats_w=4, ats_l=10),

    "Maine": profile("Maine", 19.2, 29.4, 4.5, 6.2, 1.9, 1.3,
                     -0.03, 0.05, 0.38, 0.46, 61, 0.15, 1260, sos=0.29, ats_w=4, ats_l=10),

    "New Hampshire": profile("New Hampshire", 20.4, 28.6, 4.6, 6.1, 1.9, 1.3,
                              -0.02, 0.04, 0.39, 0.45, 62, 0.15, 1280, sos=0.30, ats_w=5, ats_l=9),

    "Fordham": profile("Fordham", 18.6, 30.2, 4.4, 6.3, 2.0, 1.2,
                       -0.04, 0.05, 0.37, 0.46, 60, 0.14, 1240, sos=0.28, ats_w=4, ats_l=10),

    "Charleston Southern": profile("Charleston Southern", 17.4, 31.8, 4.2, 6.6, 2.1, 1.1,
                                    -0.06, 0.08, 0.36, 0.48, 58, 0.13, 1210, sos=0.26, ats_w=3, ats_l=11),

    "North Alabama": profile("North Alabama", 21.8, 27.4, 4.7, 6.0, 1.8, 1.4,
                              -0.01, 0.03, 0.40, 0.44, 63, 0.16, 1310, sos=0.42, ats_w=5, ats_l=9),

    "Incarnate Word": profile("Incarnate Word", 22.4, 28.6, 4.8, 6.1, 1.8, 1.3,
                               0.00, 0.02, 0.40, 0.44, 64, 0.15, 1320, sos=0.43, ats_w=5, ats_l=9),

    "Western Carolina": profile("Western Carolina", 18.8, 31.4, 4.4, 6.5, 2.0, 1.2,
                                 -0.04, 0.06, 0.37, 0.47, 60, 0.14, 1240, sos=0.27, ats_w=4, ats_l=10),

    "Southeast Missouri State": profile("Southeast Missouri State", 20.6, 28.8, 4.6, 6.1, 1.9, 1.3,
                                         -0.02, 0.04, 0.39, 0.45, 62, 0.15, 1270, sos=0.30, ats_w=5, ats_l=9),
}
