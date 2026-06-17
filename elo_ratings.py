"""
elo_ratings.py - Culture & Pulse Analytics
Self-updating Elo rating system for all sports.

How it works:
  - Every team starts at BASE_ELO (1500)
  - After each game, winner gains points, loser loses points
  - Upset wins (beating a much stronger team) gain more points
  - Home court advantage adds a small bonus before calculating win probability
  - Margin of victory multiplier makes blowouts move the rating more

Usage:
  python elo_ratings.py backfill wnba     # build Elo from all historical games
  python elo_ratings.py backfill nba
  python elo_ratings.py backfill nfl
  python elo_ratings.py backfill ncaab
  python elo_ratings.py backfill ncaaf
  python elo_ratings.py backfill all
  python elo_ratings.py top wnba          # show current Elo leaderboard
  python elo_ratings.py predict wnba "Minnesota Lynx" "Las Vegas Aces"
"""

import math
from datetime import datetime
from database import get_conn

BASE_ELO = 1500.0

# K-factor controls how much a single game moves the rating.
# Higher K = more volatile, reacts faster to recent results.
K_FACTOR = {
    "nba":   20,
    "wnba":  24,   # fewer games per season, so weight each one more
    "nfl":   28,   # very few games per season, each one matters a lot
    "ncaab": 24,
    "ncaaf": 26,
}

HOME_ADV_ELO = {
    "nba":   65,
    "wnba":  55,
    "nfl":   48,
    "ncaab": 85,   # college home court is huge
    "ncaaf": 75,
}

# Margin of victory multiplier dampens blowout overreaction
# using the standard log-based formula from FiveThirtyEight's NFL Elo model.
MOV_DAMPENING = {
    "nba":   True,
    "wnba":  True,
    "nfl":   True,
    "ncaab": True,
    "ncaaf": True,
}


def init_elo_tables():
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS elo_ratings (
            sport       TEXT NOT NULL,
            team_name   TEXT NOT NULL,
            elo         REAL DEFAULT 1500.0,
            games_played INTEGER DEFAULT 0,
            last_updated TEXT,
            PRIMARY KEY (sport, team_name)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS elo_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sport       TEXT NOT NULL,
            date        TEXT NOT NULL,
            home_team   TEXT NOT NULL,
            away_team   TEXT NOT NULL,
            home_elo_before REAL,
            away_elo_before REAL,
            home_elo_after  REAL,
            away_elo_after  REAL,
            winner      TEXT
        )
    """)
    conn.commit()
    conn.close()


def get_elo(team_name: str, sport: str) -> float:
    """Returns current Elo for a team, or BASE_ELO if not yet rated."""
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT elo FROM elo_ratings WHERE sport = ? AND team_name = ?
    """, (sport, team_name))
    row = c.fetchone()
    conn.close()
    return row["elo"] if row else BASE_ELO


def expected_win_prob(elo_a: float, elo_b: float) -> float:
    """Standard Elo expected score formula."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def mov_multiplier(margin: int, elo_diff: float) -> float:
    """
    Margin of victory multiplier, dampened by how big the elo
    favorite already was -- prevents big favorites from gaining
    huge extra credit for expected blowouts.
    """
    if margin <= 0:
        margin = 1
    return math.log(margin + 1) * (2.2 / ((elo_diff * 0.001) + 2.2))


def update_elo(sport: str, home_team: str, away_team: str,
                home_score: int, away_score: int, date: str = None) -> tuple:
    """
    Updates Elo ratings for both teams after a game result.
    Returns (new_home_elo, new_away_elo).
    """
    k         = K_FACTOR.get(sport, 24)
    home_adv  = HOME_ADV_ELO.get(sport, 60)
    use_mov   = MOV_DAMPENING.get(sport, True)

    home_elo = get_elo(home_team, sport)
    away_elo = get_elo(away_team, sport)

    # Home court advantage baked into expected win prob calc
    home_elo_adj = home_elo + home_adv

    expected_home = expected_win_prob(home_elo_adj, away_elo)
    expected_away = 1.0 - expected_home

    home_won  = home_score > away_score
    actual_home = 1.0 if home_won else 0.0
    actual_away = 1.0 - actual_home

    margin    = abs(home_score - away_score)
    elo_diff  = abs(home_elo_adj - away_elo)
    mult      = mov_multiplier(margin, elo_diff) if use_mov else 1.0

    new_home_elo = home_elo + k * mult * (actual_home - expected_home)
    new_away_elo = away_elo + k * mult * (actual_away - expected_away)

    conn = get_conn()
    c    = conn.cursor()

    for team, new_elo in [(home_team, new_home_elo), (away_team, new_away_elo)]:
        c.execute("""
            INSERT INTO elo_ratings (sport, team_name, elo, games_played, last_updated)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(sport, team_name) DO UPDATE SET
                elo = ?,
                games_played = games_played + 1,
                last_updated = ?
        """, (sport, team, new_elo, date, new_elo, date))

    c.execute("""
        INSERT INTO elo_history
        (sport, date, home_team, away_team, home_elo_before, away_elo_before,
         home_elo_after, away_elo_after, winner)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        sport, date, home_team, away_team,
        round(home_elo, 1), round(away_elo, 1),
        round(new_home_elo, 1), round(new_away_elo, 1),
        home_team if home_won else away_team,
    ))

    conn.commit()
    conn.close()

    return round(new_home_elo, 1), round(new_away_elo, 1)

def is_exhibition_team(team_name: str) -> bool:
    """
    Filters out All-Star teams, exhibition matchups, and international
    friendlies that pollute historical game data but aren't real franchises.
    """
    junk_keywords = [
        "team ", "world", "usa", "rest of", "stars", "all-star",
        "select team", "international",
    ]
    name_lower = team_name.lower()
    return any(kw in name_lower for kw in junk_keywords)
def backfill_elo(sport: str):
    """
    Rebuilds Elo ratings from scratch using full head_to_head history,
    processed in chronological order.
    """
    init_elo_tables()

    conn = get_conn()
    c    = conn.cursor()

    # Reset existing ratings for this sport before rebuilding
    c.execute("DELETE FROM elo_ratings WHERE sport = ?", (sport,))
    c.execute("DELETE FROM elo_history WHERE sport = ?", (sport,))
    conn.commit()

    c.execute("""
        SELECT home_team, away_team, home_score, away_score, date, winner
        FROM head_to_head
        WHERE sport = ?
        ORDER BY date ASC
    """, (sport,))

    rows = c.fetchall()
    conn.close()

    print(f"\nBackfilling {sport.upper()} Elo from {len(rows)} historical games...")

    processed = 0
    skipped   = 0
    for row in rows:
        if row["home_score"] is None or row["away_score"] is None:
            continue
        if is_exhibition_team(row["home_team"]) or is_exhibition_team(row["away_team"]):
            skipped += 1
            continue
        update_elo(
            sport, row["home_team"], row["away_team"],
            row["home_score"], row["away_score"], date=row["date"]
        )
        processed += 1

    print(f"  Skipped {skipped} exhibition/all-star game(s)")

    print(f"Elo backfill complete: {processed} games processed")


def print_elo_leaderboard(sport: str, limit: int = 20, hbcu_only: bool = False):
    conn = get_conn()
    c    = conn.cursor()

    if hbcu_only and sport.startswith("hbcu_"):
        from hbcu_teams import get_team_registry
        registry_key = sport
        registry = get_team_registry(registry_key)
        hbcu_names = list(registry.keys())
        placeholders = ",".join("?" * len(hbcu_names))
        c.execute(f"""
            SELECT team_name, elo, games_played FROM elo_ratings
            WHERE sport = ? AND team_name IN ({placeholders})
            ORDER BY elo DESC
            LIMIT ?
        """, (sport, *hbcu_names, limit))
    else:
        c.execute("""
            SELECT team_name, elo, games_played FROM elo_ratings
            WHERE sport = ?
            ORDER BY elo DESC
            LIMIT ?
        """, (sport, limit))

    rows = c.fetchall()
    conn.close()

    print(f"\n{'='*55}")
    print(f"  {sport.upper()} ELO RATINGS")
    print(f"{'='*55}")
    print(f"  {'Team':<30} {'Elo':<8} {'Games'}")
    print(f"  {'-'*48}")
    for r in rows:
        print(f"  {r['team_name']:<30} {round(r['elo'],1):<8} {r['games_played']}")
    print(f"{'='*55}\n")


def predict_with_elo(home_team: str, away_team: str, sport: str) -> dict:
    """Returns Elo-based win probability for a matchup."""
    home_adv = HOME_ADV_ELO.get(sport, 60)
    home_elo = get_elo(home_team, sport)
    away_elo = get_elo(away_team, sport)

    home_elo_adj = home_elo + home_adv
    home_prob    = expected_win_prob(home_elo_adj, away_elo)

    return {
        "home_team":  home_team,
        "away_team":  away_team,
        "home_elo":   round(home_elo, 1),
        "away_elo":   round(away_elo, 1),
        "home_win_prob": round(home_prob * 100, 1),
        "away_win_prob": round((1 - home_prob) * 100, 1),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == "backfill":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            if sport == "all":
                for s in ["wnba", "nba", "nfl", "ncaab", "ncaaf"]:
                    backfill_elo(s)
                    print_elo_leaderboard(s, limit=10)
            else:
                backfill_elo(sport)
                print_elo_leaderboard(sport, limit=20, hbcu_only=sport.startswith("hbcu_"))

        elif cmd == "top":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            print_elo_leaderboard(sport, limit=20, hbcu_only=sport.startswith("hbcu_"))

        elif cmd == "predict":
            if len(sys.argv) < 5:
                print("Usage: python elo_ratings.py predict [sport] [home] [away]")
            else:
                sport     = sys.argv[2].lower()
                home_team = sys.argv[3]
                away_team = sys.argv[4]
                result    = predict_with_elo(home_team, away_team, sport)
                print(f"\n{result['away_team']} ({result['away_elo']}) @ "
                      f"{result['home_team']} ({result['home_elo']})")
                print(f"  Home win prob: {result['home_win_prob']}%")
                print(f"  Away win prob: {result['away_win_prob']}%")
    else:
        print("Usage: python elo_ratings.py [backfill|top|predict] [sport] [args]")
