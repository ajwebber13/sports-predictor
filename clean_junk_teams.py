"""
clean_junk_teams.py - One-time cleanup
Removes international/exhibition teams from all WNBA tables
then rebuilds Elo from clean data.
"""
from database import get_conn

JUNK_TEAMS = [
    "WEST", "EAST", "Puerto Rico", "NIGERIA", "Toyota Antelopes",
    "Brazil", "CHINA", "Australia", "Canada", "France", "Spain",
    "Team Wilson", "TEAM STEWART", "Team Stewart", "Team Wilson",
]

def clean():
    conn = get_conn()
    c    = conn.cursor()

    total_h2h = 0
    total_elo = 0
    total_his = 0

    for team in JUNK_TEAMS:
        # head_to_head — the source that feeds backfill
        c.execute("""
            DELETE FROM head_to_head
            WHERE sport = 'wnba'
            AND (home_team = ? OR away_team = ?)
        """, (team, team))
        total_h2h += c.rowcount

        # elo_ratings
        c.execute("DELETE FROM elo_ratings WHERE sport = 'wnba' AND team_name = ?", (team,))
        total_elo += c.rowcount

        # elo_history
        c.execute("""
            DELETE FROM elo_history
            WHERE sport = 'wnba'
            AND (home_team = ? OR away_team = ?)
        """, (team, team))
        total_his += c.rowcount

        if total_h2h > 0 or total_elo > 0 or total_his > 0:
            print(f"  Removed {team}: h2h={c.rowcount}")

    conn.commit()
    conn.close()

    print(f"\n  Total removed:")
    print(f"  head_to_head: {total_h2h} rows")
    print(f"  elo_ratings:  {total_elo} rows")
    print(f"  elo_history:  {total_his} rows")
    print(f"\n  Now run: python elo_ratings.py backfill wnba")

if __name__ == "__main__":
    clean()
