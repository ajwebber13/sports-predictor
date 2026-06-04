"""
Run from C:\temp\sports_predictor:
  python fix_wnba_ids.py
"""

content = open('wnba_data.py').read()

fixes = {
    '"Dallas Wings":            "26"': '"Dallas Wings":            "3"',
    '"Golden State Valkyries":  "30"': '"Golden State Valkyries":  "129689"',
    '"Indiana Fever":           "25"': '"Indiana Fever":           "5"',
    '"Las Vegas Aces":          "23"': '"Las Vegas Aces":          "17"',
    '"Los Angeles Sparks":      "14"': '"Los Angeles Sparks":      "6"',
    '"Minnesota Lynx":          "16"': '"Minnesota Lynx":          "8"',
    '"New York Liberty":        "21"': '"New York Liberty":        "9"',
    '"Phoenix Mercury":         "15"': '"Phoenix Mercury":         "11"',
    '"Seattle Storm":           "17"': '"Seattle Storm":           "14"',
    '"Washington Mystics":      "24"': '"Washington Mystics":      "16"',
}

for old, new in fixes.items():
    content = content.replace(old, new)

if 'Portland Fire' not in content:
    content = content.replace(
        '"Washington Mystics":      "16",',
        '"Washington Mystics":      "16",\n    "Portland Fire":           "132052",\n    "Toronto Tempo":           "131935",'
    )

with open('wnba_data.py', 'w') as f:
    f.write(content)

print('Done - verifying...')
import importlib, sys
if 'wnba_data' in sys.modules:
    del sys.modules['wnba_data']
import wnba_data
print('Teams:', list(wnba_data.TEAM_IDS.keys()))
