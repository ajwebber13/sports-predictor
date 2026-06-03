"""
Run this to add missing teams to wnba_profiles.py:
  python add_teams.py
"""
import os

addition = '''
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
'''

path = 'data/wnba_profiles.py'
content = open(path).read()

# Replace the closing } with new teams + }
if content.rstrip().endswith('}'):
    # Remove last }
    content = content.rstrip()[:-1]
    # Add new teams
    content = content + addition

    with open(path, 'w') as f:
        f.write(content)
    print('Done - added LA Sparks, Portland Fire, Toronto Tempo')
else:
    print('Could not find closing brace - check file manually')
