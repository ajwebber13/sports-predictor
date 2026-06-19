"""
elo_ratings.py - Culture & Pulse Analytics
Self-updating Elo rating system for all sports.

How it works:
  - Every team starts at BASE_ELO (1500)
  - After each game, winner gains points, loser loses points
  - Upset wins (beating a much stronger team) gain more points
  - Home court advantage adds a small bonus before calculating win probability
  - Margin of victory multiplier makes blowouts move the rating more
  - Dynamic K-factor: higher early in season, stabilizes after 15 games
  - Annual recalibration regresses ratings toward mean at season start

Usage:
  python elo_ratings.py backfill wnba     # build Elo from all historical games
  python elo_ratings.py backfill all
  python elo_ratings.py top wnba          # show current Elo leaderboard
  python elo_ratings.py predict wnba "Minnesota Lynx" "Las Vegas Aces"
  python elo_ratings.py recalibrate wnba  # run season-start recalibration
  python elo_ratings.py recalibrate all
"""

import math
from datetime import datetime
from database import get_conn

BASE_ELO = 1500.0

# Base K-factor per sport. Dynamic K (see get_k_factor) scales this
# higher early in the season and lower once ratings have stabilized.
K_FACTOR_BASE = {
    "nba":          20,
    "wnba":         24,   # fewer games per season — weight each one more
    "nfl":          28,   # very few games — each one matters a lot
    "ncaab":        24,
    "ncaaf":        26,
    "hbcu_football":26,
    "hbcu_mbb":     24,
    "hbcu_wbb":     24,
}

HOME_ADV_ELO = {
    "nba":          65,
    "wnba":         55,
    "nfl":          48,
    "ncaab":        85,
    "ncaaf":        75,
    "hbcu_football":70,
    "hbcu_mbb":     80,
    "hbcu_wbb":     75,
}

MOV_DAMPENING = {
    "nba": True, "wnba": True, "nfl": True,
    "ncaab": True, "ncaaf": True,
    "hbcu_football": True, "hbcu_mbb": True, "hbcu_wbb": True,
}

# Season game counts — used for dynamic K scaling
# Update WNBA to 50 when new schedule confirmed
SEASON_GAMES = {
    "nba":          82,
    "wnba":         50,   # expanding to 50 games in new season
    "nfl":          17,
    "ncaab":        30,
    "ncaaf":        12,
    "hbcu_football":10,
    "hbcu_mbb":     28,
    "hbcu_wbb":     28,
}

# Regression to mean at season start (0.25 = 25% pull toward 1500)
MEAN_REGRESSION = 0.25

# Expansion teams start below mean — less than neutral
EXPANSION_ELO = 1400.0
EXPANSION_TEAMS = {
    "wnba": ["Golden State Valkyries", "Toronto Tempo", "Portland Fire"],
}


# ─────────────────────────────────────────────────────────────
# DB INIT
# ─────────────────────────────────────────────────────────────

def init_elo_tables():
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS elo_ratings (
            sport        TEXT NOT NULL,
            team_name    TEXT NOT NULL,
            elo          REAL DEFAULT 1500.0,
            games_played INTEGER DEFAULT 0,
            last_updated TEXT,
            PRIMARY KEY (sport, team_name)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS elo_history (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            sport            TEXT NOT NULL,
            date             TEXT NOT NULL,
            home_team        TEXT NOT NULL,
            away_team        TEXT NOT NULL,
            home_elo_before  REAL,
            away_elo_before  REAL,
            home_elo_after   REAL,
            away_elo_after   REAL,
            winner           TEXT
        )
    """)
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────
# CORE ELO MATH
# ─────────────────────────────────────────────────────────────

def get_elo(team_name: str, sport: str) -> float:
    """Returns current Elo for a team, or BASE_ELO if not yet rated."""
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT elo FROM elo_ratings WHERE sport = ? AND team_name = ?",
              (sport, team_name))
    row = c.fetchone()
    conn.close()
    return row["elo"] if row else BASE_ELO


def get_games_played(team_name: str, sport: str) -> int:
    """Returns games played this season for dynamic K scaling."""
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT games_played FROM elo_ratings WHERE sport = ? AND team_name = ?",
              (sport, team_name))
    row = c.fetchone()
    conn.close()
    return row["games_played"] if row else 0


def get_k_factor(sport: str, games_played: int) -> float:
    """
    Dynamic K-factor. Higher early in season (ratings settling),
    lower once enough games played to trust the rating.

    Early season (0-14 games):  K * 1.4  — react faster to new data
    Mid season  (15-29 games):  K * 1.0  — standard
    Late season (30+ games):    K * 0.8  — ratings stable, dampen swings

    With WNBA expanding to 50 games, this matters more than ever.
    """
    base = K_FACTOR_BASE.get(sport, 24)
    if games_played < 15:
        return base * 1.4
    if games_played < 30:
        return base * 1.0
    return base * 0.8


def expected_win_prob(elo_a: float, elo_b: float) -> float:
    """Standard Elo expected score formula."""
    return 1.0 / (1.0 + 10 ** ((elo_b - elo_a) / 400.0))


def mov_multiplier(margin: int, elo_diff: float) -> float:
    """
    Margin of victory multiplier, dampened by how big the Elo
    favorite already was. Prevents big favorites from gaining
    huge extra credit for expected blowouts.
    Based on FiveThirtyEight's NFL Elo model formula.
    """
    if margin <= 0:
        margin = 1
    return math.log(margin + 1) * (2.2 / ((elo_diff * 0.001) + 2.2))


def is_exhibition_team(team_name: str) -> bool:
    """Filter out All-Star, exhibition, and international game entries."""
    junk = ["team ", "world", "usa", "rest of", "stars", "all-star",
            "select team", "international"]
    n = team_name.lower()
    return any(kw in n for kw in junk)


# ─────────────────────────────────────────────────────────────
# ELO UPDATE
# ─────────────────────────────────────────────────────────────

def update_elo(sport: str, home_team: str, away_team: str,
               home_score: int, away_score: int, date: str = None) -> tuple:
    """
    Updates Elo ratings for both teams after a game result.
    Uses dynamic K-factor based on games played.
    Returns (new_home_elo, new_away_elo).
    """
    home_adv = HOME_ADV_ELO.get(sport, 60)
    use_mov  = MOV_DAMPENING.get(sport, True)

    home_elo = get_elo(home_team, sport)
    away_elo = get_elo(away_team, sport)

    home_games = get_games_played(home_team, sport)
    away_games = get_games_played(away_team, sport)

    # Use average of both teams' games played for K
    avg_games = (home_games + away_games) / 2
    k         = get_k_factor(sport, avg_games)

    home_elo_adj  = home_elo + home_adv
    expected_home = expected_win_prob(home_elo_adj, away_elo)
    expected_away = 1.0 - expected_home

    home_won    = home_score > away_score
    actual_home = 1.0 if home_won else 0.0
    actual_away = 1.0 - actual_home

    margin   = abs(home_score - away_score)
    elo_diff = abs(home_elo_adj - away_elo)
    mult     = mov_multiplier(margin, elo_diff) if use_mov else 1.0

    new_home_elo = home_elo + k * mult * (actual_home - expected_home)
    new_away_elo = away_elo + k * mult * (actual_away - expected_away)

    conn = get_conn()
    c    = conn.cursor()

    for team, new_elo in [(home_team, new_home_elo), (away_team, new_away_elo)]:
        c.execute("""
            INSERT INTO elo_ratings (sport, team_name, elo, games_played, last_updated)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(sport, team_name) DO UPDATE SET
                elo          = ?,
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


# ─────────────────────────────────────────────────────────────
# SEASON RECALIBRATION
# ─────────────────────────────────────────────────────────────

def recalibrate_season(sport: str, dry_run: bool = False):
    """
    Annual season-start recalibration.

    Run this every year before the first game of the new season.

    What it does:
    1. Regresses all ratings 25% toward 1500 (mean regression)
       - A team at 1600 moves to 1575 (25% of the 100-point gap closed)
       - A team at 1400 moves to 1425
       - Accounts for roster turnover, coaching changes, offseason uncertainty
    2. Resets games_played to 0 so dynamic K starts high again
    3. Sets expansion teams to EXPANSION_ELO (1400) if first season
    4. Logs the recalibration so you can track year-over-year movement

    Why 25%: Standard in Elo systems. FiveThirtyEight uses 1/3.
    Lower means you trust last season more. Higher means more uncertainty.
    """
    init_elo_tables()

    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT team_name, elo, games_played FROM elo_ratings WHERE sport = ?",
              (sport,))
    teams = c.fetchall()
    conn.close()

    if not teams:
        print(f"  No {sport.upper()} ratings found. Run backfill first.")
        return

    expansion = EXPANSION_TEAMS.get(sport, [])
    today     = datetime.now().strftime("%Y-%m-%d")

    print(f"\n{'═'*55}")
    print(f"  📅 SEASON RECALIBRATION — {sport.upper()}")
    print(f"  Date: {today}")
    print(f"  Regression: {int(MEAN_REGRESSION*100)}% toward {BASE_ELO}")
    print(f"{'═'*55}")
    print(f"  {'Team':<28} {'Before':>8}  {'After':>8}  {'Change':>8}")
    print(f"  {'─'*52}")

    updates = []
    for team in teams:
        name    = team["team_name"]
        old_elo = team["elo"]

        if name in expansion and team["games_played"] < 20:
            # Expansion team with very little history — reset to expansion baseline
            new_elo = EXPANSION_ELO
        else:
            # Standard mean regression
            new_elo = old_elo + MEAN_REGRESSION * (BASE_ELO - old_elo)

        new_elo = round(new_elo, 1)
        change  = round(new_elo - old_elo, 1)
        sign    = "+" if change >= 0 else ""
        print(f"  {name:<28} {round(old_elo,1):>8.1f}  {new_elo:>8.1f}  {sign}{change:>7.1f}")
        updates.append((name, new_elo))

    print(f"{'═'*55}")

    if dry_run:
        print(f"\n  DRY RUN — no changes written. Remove --dry-run to apply.")
        return

    conn = get_conn()
    c    = conn.cursor()
    for name, new_elo in updates:
        c.execute("""
            UPDATE elo_ratings
            SET elo = ?, games_played = 0, last_updated = ?
            WHERE sport = ? AND team_name = ?
        """, (new_elo, today, sport, name))
    conn.commit()
    conn.close()

    print(f"\n  ✅ {len(updates)} teams recalibrated. games_played reset to 0.")
    print(f"     Dynamic K-factor will now start high for the new season.")
    print(f"     Run 'python elo_ratings.py top {sport}' to verify.\n")


# ─────────────────────────────────────────────────────────────
# BACKFILL
# ─────────────────────────────────────────────────────────────

def backfill_elo(sport: str):
    """
    Rebuilds Elo ratings from scratch using full head_to_head history,
    processed in chronological order.
    """
    init_elo_tables()

    conn = get_conn()
    c    = conn.cursor()

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
    print(f"  Backfill complete: {processed} games processed")


# ─────────────────────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────────────────────

def print_elo_leaderboard(sport: str, limit: int = 20, hbcu_only: bool = False):
    conn = get_conn()
    c    = conn.cursor()

    if hbcu_only and sport.startswith("hbcu_"):
        from hbcu_teams import get_team_registry
        registry  = get_team_registry(sport)
        hbcu_names = list(registry.keys())
        placeholders = ",".join("?" * len(hbcu_names))
        c.execute(f"""
            SELECT team_name, elo, games_played FROM elo_ratings
            WHERE sport = ? AND team_name IN ({placeholders})
            ORDER BY elo DESC LIMIT ?
        """, (sport, *hbcu_names, limit))
    else:
        c.execute("""
            SELECT team_name, elo, games_played FROM elo_ratings
            WHERE sport = ? ORDER BY elo DESC LIMIT ?
        """, (sport, limit))

    rows = c.fetchall()
    conn.close()

    print(f"\n{'='*55}")
    print(f"  {sport.upper()} ELO RATINGS")
    print(f"{'='*55}")
    print(f"  {'Team':<30} {'Elo':<10} {'Games'}")
    print(f"  {'-'*48}")
    for r in rows:
        print(f"  {r['team_name']:<30} {round(r['elo'],1):<10} {r['games_played']}")
    print(f"{'='*55}\n")


# ─────────────────────────────────────────────────────────────
# PREDICTION
# ─────────────────────────────────────────────────────────────

def predict_with_elo(home_team: str, away_team: str, sport: str) -> dict:
    """Returns Elo-based win probability for a matchup."""
    home_adv     = HOME_ADV_ELO.get(sport, 60)
    home_elo     = get_elo(home_team, sport)
    away_elo     = get_elo(away_team, sport)
    home_elo_adj = home_elo + home_adv
    home_prob    = expected_win_prob(home_elo_adj, away_elo)

    return {
        "home_team":     home_team,
        "away_team":     away_team,
        "home_elo":      round(home_elo, 1),
        "away_elo":      round(away_elo, 1),
        "home_win_prob": round(home_prob * 100, 1),
        "away_win_prob": round((1 - home_prob) * 100, 1),
    }


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

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
                print_elo_leaderboard(sport, limit=20,
                                      hbcu_only=sport.startswith("hbcu_"))

        elif cmd == "top":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            print_elo_leaderboard(sport, limit=20,
                                  hbcu_only=sport.startswith("hbcu_"))

        elif cmd == "recalibrate":
            sport   = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            dry_run = "--dry-run" in sys.argv
            if sport == "all":
                for s in ["wnba", "nba", "nfl", "ncaab", "ncaaf"]:
                    recalibrate_season(s, dry_run=dry_run)
            else:
                recalibrate_season(sport, dry_run=dry_run)

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
        print("Usage: python elo_ratings.py [backfill|top|recalibrate|predict] [sport] [args]")
