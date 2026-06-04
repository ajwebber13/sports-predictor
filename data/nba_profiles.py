"""
data/nba_profiles.py
=====================
EnhancedProfile objects for all 30 NBA teams.
Stats based on 2024-25 season.
League = "NFL" used as proxy for NBA scoring range.
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

def nba(name, pts_off, pts_def, pace, net_rtg, elo, ats_w, ats_l, sos=0.50):
    # Use NFL league as proxy — pts scaled down for rating engine
    # NBA pts/100 poss range ~105-120, we use actual pts/game
    epa_off = round((pts_off - 113.0) / 15.0, 3)
    epa_def = round((113.0 - pts_def) / 15.0, 3)
    return EnhancedProfile(
        team_name    = name, league="NBA",
        pts_off      = pts_off, pts_def=pts_def,
        ypp_off      = round(pts_off / 20.0, 2),
        ypp_def      = round(pts_def / 20.0, 2),
        to_given     = 13.5, to_forced=13.5,
        home_pts_off = round(pts_off * 1.02, 1),
        away_pts_off = round(pts_off * 0.98, 1),
        recent_off   = pts_off, recent_def=pts_def,
        sos=sos, injury_adj=0.0,
        advanced     = adv(epa_off, epa_def, 0.52, 0.52, pace, 0.18, elo),
        history      = hist(pts_off, pts_def, 0.0, 0.0),
        ats          = ats(ats_w, ats_l),
    )


NBA_PROFILES = {

    # ─── EASTERN CONFERENCE ───────────────────────────────────

    # Atlantic
    "Boston Celtics":       nba("Boston Celtics",       120.6, 107.4, 100.2, 13.2, 1820, 52, 30),
    "New York Knicks":      nba("New York Knicks",       113.5, 108.4, 96.8,  5.1, 1680, 50, 32),
    "Philadelphia 76ers":   nba("Philadelphia 76ers",   112.8, 112.6, 99.4,  0.2, 1580, 38, 44),
    "Brooklyn Nets":        nba("Brooklyn Nets",         107.2, 117.8, 97.6, -10.6, 1390, 22, 60),
    "Toronto Raptors":      nba("Toronto Raptors",       108.4, 115.6, 98.8,  -7.2, 1420, 25, 57),

    # Central
    "Cleveland Cavaliers":  nba("Cleveland Cavaliers",  114.8, 107.2, 95.6,  7.6, 1720, 49, 33),
    "Indiana Pacers":       nba("Indiana Pacers",        119.4, 117.2, 103.8,  2.2, 1580, 44, 38),
    "Milwaukee Bucks":      nba("Milwaukee Bucks",       115.6, 113.4, 101.2,  2.2, 1610, 42, 40),
    "Chicago Bulls":        nba("Chicago Bulls",         110.2, 113.8, 99.6,  -3.6, 1480, 39, 43),
    "Detroit Pistons":      nba("Detroit Pistons",       108.6, 116.4, 100.4,  -7.8, 1420, 28, 54),

    # Southeast
    "Miami Heat":           nba("Miami Heat",            110.8, 110.6, 97.2,  0.2, 1590, 42, 40),
    "Orlando Magic":        nba("Orlando Magic",         108.4, 106.8, 96.4,  1.6, 1580, 41, 41),
    "Atlanta Hawks":        nba("Atlanta Hawks",          114.6, 116.2, 101.8,  -1.6, 1490, 36, 46),
    "Charlotte Hornets":    nba("Charlotte Hornets",     108.2, 117.4, 100.6,  -9.2, 1380, 19, 63),
    "Washington Wizards":   nba("Washington Wizards",    105.8, 119.6, 99.8, -13.8, 1320, 18, 64),

    # ─── WESTERN CONFERENCE ───────────────────────────────────

    # Northwest
    "Oklahoma City Thunder": nba("Oklahoma City Thunder", 118.6, 107.8, 99.8, 10.8, 1780, 57, 25),
    "Denver Nuggets":        nba("Denver Nuggets",        115.4, 111.2, 97.6,  4.2, 1680, 50, 32),
    "Minnesota Timberwolves":nba("Minnesota Timberwolves",113.8, 108.4, 98.2,  5.4, 1660, 49, 33),
    "Utah Jazz":             nba("Utah Jazz",             108.4, 118.6, 100.2, -10.2, 1380, 21, 61),
    "Portland Trail Blazers":nba("Portland Trail Blazers",107.6, 117.4, 99.4, -9.8, 1390, 21, 61),

    # Pacific
    "Golden State Warriors": nba("Golden State Warriors", 116.2, 113.4, 100.6,  2.8, 1640, 46, 36),
    "Los Angeles Lakers":    nba("Los Angeles Lakers",    113.8, 113.2, 98.8,  0.6, 1610, 44, 38),
    "Los Angeles Clippers":  nba("Los Angeles Clippers",  111.4, 111.8, 97.4, -0.4, 1560, 41, 41),
    "Phoenix Suns":          nba("Phoenix Suns",          113.6, 116.2, 100.4, -2.6, 1520, 36, 46),
    "Sacramento Kings":      nba("Sacramento Kings",      116.8, 117.4, 101.8, -0.6, 1540, 39, 43),

    # Southwest
    "San Antonio Spurs":     nba("San Antonio Spurs",     113.2, 118.4, 99.6,  -5.2, 1480, 34, 48),
    "Dallas Mavericks":      nba("Dallas Mavericks",      117.4, 114.2, 100.8,  3.2, 1650, 47, 35),
    "Houston Rockets":       nba("Houston Rockets",       112.6, 108.8, 97.8,  3.8, 1620, 49, 33),
    "Memphis Grizzlies":     nba("Memphis Grizzlies",     114.8, 115.6, 101.4, -0.8, 1530, 39, 43),
    "New Orleans Pelicans":  nba("New Orleans Pelicans",  109.4, 114.8, 98.6,  -5.4, 1440, 28, 54),
}
