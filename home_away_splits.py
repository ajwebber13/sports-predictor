"""
home_away_splits.py - Culture & Pulse Analytics
Calculates each team's true home/away scoring split using
actual game results, not just win/loss record.

Some teams are dramatically better (or worse) at home than
their generic home court advantage would suggest. This layer
captures that team-specific signal from real point differentials.

Usage:
  python home_away_splits.py build wnba     # calculate splits for all teams
  python home_away_splits.py build all
  python home_away_splits.py top wnba       # show biggest home/away gaps
  python home_away_splits.py check wnba "Minnesota Lynx"
"""

from database import get_conn
from datetime import datetime


def init_splits_table():
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS home_away_splits (
            sport            TEXT NOT NULL,
            team_name        TEXT NOT NULL,
            home_games       INTEGER DEFAULT 0,
            away_games       INTEGER DEFAULT 0,
            home_avg_margin  REAL DEFAULT 0.0,
            away_avg_margin  REAL DEFAULT 0.0,
            home_away_gap    REAL DEFAULT 0.0,
            home_win_pct     REAL DEFAULT 0.0,
            away_win_pct     REAL DEFAULT 0.0,
            last_updated     TEXT,
            PRIMARY KEY (sport, team_name)
        )
    """)
    conn.commit()
    conn.close()


def build_splits(sport: str):
    """MIGRATION NOTE (2026-07-14): disabled, not converted.

    This reads FROM head_to_head, which — like backfill.py's
    backfill_head_to_head() — was confirmed to not exist in the live
    Turso database. This function has therefore never been able to
    produce real output; calling it would crash outright on "no such
    table: head_to_head" (there's no try/except around that SELECT).

    Same reasoning as disabling backfill_head_to_head(): this isn't a
    migration bug to patch by inventing a head_to_head table in
    schema_postgres.sql, it's a feature that depends entirely on data
    that's never existed. get_split_adjustment() below already
    degrades gracefully — it returns 0.0 whenever home_away_splits is
    empty (which it always has been), so disabling this write path
    changes nothing about live prediction behavior. If head-to-head
    tracking gets built as a real feature later, this can be revisited
    alongside it."""
    print(f"  build_splits() is disabled — depends on the head_to_head "
          f"table, which was never created in production. Skipping {sport}.")
    return


def _unused_build_splits(sport: str):
    """
    Calculates home/away point margin splits for every team
    using the head_to_head table.
    """
    init_splits_table()

    conn = get_conn()
    c    = conn.cursor()

    # Clear old data for this sport before rebuilding
    c.execute("DELETE FROM home_away_splits WHERE sport = ?", (sport,))
    conn.commit()

    c.execute("""
        SELECT home_team, away_team, home_score, away_score
        FROM head_to_head
        WHERE sport = ? AND home_score IS NOT NULL AND away_score IS NOT NULL
    """, (sport,))
    raw_rows = c.fetchall()

    def is_exhibition(name):
        junk = ["team ", "world", "usa", "rest of", "stars", "all-star", "select team"]
        n = name.lower()
        return any(k in n for k in junk)

    rows = [r for r in raw_rows if not is_exhibition(r["home_team"]) and not is_exhibition(r["away_team"])]

    team_data = {}

    for row in rows:
        home, away = row["home_team"], row["away_team"]
        h_score, a_score = row["home_score"], row["away_score"]
        margin = h_score - a_score

        team_data.setdefault(home, {"home_margins": [], "away_margins": [],
                                     "home_wins": 0, "home_games": 0,
                                     "away_wins": 0, "away_games": 0})
        team_data.setdefault(away, {"home_margins": [], "away_margins": [],
                                     "home_wins": 0, "home_games": 0,
                                     "away_wins": 0, "away_games": 0})

        team_data[home]["home_margins"].append(margin)
        team_data[home]["home_games"] += 1
        if margin > 0:
            team_data[home]["home_wins"] += 1

        team_data[away]["away_margins"].append(-margin)
        team_data[away]["away_games"] += 1
        if margin < 0:
            team_data[away]["away_wins"] += 1

    saved = 0
    for team, d in team_data.items():
        home_games = d["home_games"]
        away_games = d["away_games"]

        if home_games == 0 or away_games == 0:
            continue

        home_avg = round(sum(d["home_margins"]) / home_games, 2)
        away_avg = round(sum(d["away_margins"]) / away_games, 2)
        gap      = round(home_avg - away_avg, 2)
        home_pct = round(d["home_wins"] / home_games, 3)
        away_pct = round(d["away_wins"] / away_games, 3)

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("""
            INSERT INTO home_away_splits
            (sport, team_name, home_games, away_games, home_avg_margin,
             away_avg_margin, home_away_gap, home_win_pct, away_win_pct, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sport, team_name) DO UPDATE SET
                home_games = ?, away_games = ?, home_avg_margin = ?,
                away_avg_margin = ?, home_away_gap = ?, home_win_pct = ?,
                away_win_pct = ?, last_updated = ?
        """, (
            sport, team, home_games, away_games, home_avg, away_avg, gap,
            home_pct, away_pct, now_str,
            home_games, away_games, home_avg, away_avg, gap, home_pct, away_pct, now_str,
        ))
        saved += 1

    conn.commit()
    conn.close()
    print(f"{sport.upper()} splits built: {saved} teams")


def get_split_adjustment(team_name: str, sport: str, is_home: bool) -> float:
    """
    Returns a point adjustment based on how this team performs
    relative to a neutral expectation when home vs away.

    FIX 1: Minimum sample raised from 5 to 15 games per split.
            Prevents expansion teams (Golden State Valkyries) from
            getting outsized adjustments on tiny samples.

    FIX 2: Confidence weight scales adjustment by sample size.
            15-29 games = partial weight. 30+ games = full weight.
            Stops noisy early-season data from dominating the signal.
    """
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT home_avg_margin, away_avg_margin, home_away_gap, home_games, away_games
        FROM home_away_splits
        WHERE sport = ? AND team_name = ?
    """, (sport, team_name))
    row = c.fetchone()
    conn.close()

    if not row:
        return 0.0

    # Raised from 5 to 15 — need meaningful sample before trusting split
    if row["home_games"] < 15 or row["away_games"] < 15:
        return 0.0

    gap = row["home_away_gap"]

    # Scale by sample size — full weight at 30+ games per split
    sample = min(row["home_games"], row["away_games"])
    confidence_weight = min(1.0, sample / 30)

    adjustment = gap * 0.5 * confidence_weight

    if is_home:
        return round(adjustment, 2)
    else:
        return round(-adjustment, 2)


def print_leaderboard(sport: str, limit: int = 20):
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT team_name, home_avg_margin, away_avg_margin, home_away_gap,
               home_win_pct, away_win_pct, home_games, away_games
        FROM home_away_splits
        WHERE sport = ?
        ORDER BY ABS(home_away_gap) DESC
        LIMIT ?
    """, (sport, limit))
    rows = c.fetchall()
    conn.close()

    print(f"\n{'='*85}")
    print(f"  {sport.upper()} HOME/AWAY SPLITS — biggest gaps first")
    print(f"{'='*85}")
    print(f"  {'Team':<26} {'Home Avg':<10} {'Away Avg':<10} {'Gap':<8} {'Home%':<8} {'Away%':<8} {'H.Games':<9} {'A.Games'}")
    print(f"  {'-'*85}")
    for r in rows:
        print(f"  {r['team_name']:<26} "
              f"{r['home_avg_margin']:<10} "
              f"{r['away_avg_margin']:<10} "
              f"{r['home_away_gap']:<8} "
              f"{round(r['home_win_pct']*100,1):<8} "
              f"{round(r['away_win_pct']*100,1):<8} "
              f"{r['home_games']:<9} "
              f"{r['away_games']}")
    print(f"{'='*85}\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == "build":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            if sport == "all":
                for s in ["wnba", "nba", "nfl", "ncaab", "ncaaf"]:
                    build_splits(s)
            else:
                build_splits(sport)
                print_leaderboard(sport)

        elif cmd == "top":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            print_leaderboard(sport)

        elif cmd == "check":
            if len(sys.argv) < 4:
                print("Usage: python home_away_splits.py check [sport] [team]")
            else:
                sport = sys.argv[2].lower()
                team  = sys.argv[3]
                home_adj = get_split_adjustment(team, sport, is_home=True)
                away_adj = get_split_adjustment(team, sport, is_home=False)
                print(f"\n{team} ({sport.upper()})")
                print(f"  Home adjustment: {home_adj:+.2f}")
                print(f"  Away adjustment: {away_adj:+.2f}")
                print(f"  Note: Returns 0.0 if team has <15 home or away games")
    else:
        print("Usage: python home_away_splits.py [build|top|check] [sport] [args]")
