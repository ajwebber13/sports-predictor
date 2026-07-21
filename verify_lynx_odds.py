"""One-off check: is that -110 for Lynx a real captured market price,
or a default/placeholder slipping through?"""
from database import get_conn
from datetime import datetime

conn = get_conn()
c = conn.cursor()
today = datetime.now().strftime("%Y-%m-%d")

c.execute("""
    SELECT date, sport, home_team, away_team, home_ml, away_ml,
           home_implied, away_implied, source, opening_home_ml, opening_away_ml
    FROM odds_history
    WHERE date = ? AND sport = 'wnba' AND home_team = 'Minnesota Lynx'
      AND away_team = 'Los Angeles Sparks'
""", (today,))
row = c.fetchone()
conn.close()

if not row:
    print("NO ROW FOUND for today's Sparks @ Lynx in odds_history.")
    print("The -110 that got logged did NOT come from a real captured price —")
    print("something else supplied it. Do not trust it.")
else:
    print("Real row found in odds_history:")
    for key in row.keys():
        print(f"  {key}: {row[key]}")
