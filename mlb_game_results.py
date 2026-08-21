"""
mlb_game_results.py — Culture & Pulse Analytics
====================================================
Derives team-level game results (one row per game: both teams, final
scores, winner) from mlb_game_log's player-level box scores. Mirrors
wnba_game_results.py's pattern exactly — see that file's docstring
for the full rationale (results is a betting ledger, not a full
season log; this derives the real games-truth layer from ESPN box
scores that get logged independently of any prediction).

MLB-specific differences from the WNBA version:
  - Team score is derived from SUM(runs), not SUM(pts) — mlb_game_log's
    batting stats use "runs" as the scoring column (see prop_tracker.py's
    fetch_espn_box_scores() MLB branch, which reads the same source data
    and confirms "runs" as the real ESPN key).
  - MLB games cannot end in a tie (extra innings always produce a
    winner) — a derived tie here is unambiguously a data error, same
    skip-and-report behavior as the WNBA version, not a special case.
  - Doubleheaders: two games between the same two teams on the same
    date will collide under (date, frozenset(teams)) — this version
    is knowingly NOT doubleheader-safe yet (same gap auto_results.py
    had before its 2026-07-24 DH fix). A doubleheader will have its
    second game silently overwrite the first via the ON CONFLICT
    upsert. Flagged, not hidden: doubleheader_collisions is counted
    and reported so this is visible rather than a silent undercount.
    Fixing this properly needs a start_time tiebreaker like
    auto_results.py's match_game() uses, deferred until this is
    confirmed needed (i.e. only if the reported count is nonzero).

Schema: uses the SAME team_game_results table wnba_game_results.py
creates (UNIQUE(sport, date, home_team, away_team), sport='mlb' here)
— no new table needed, just a new sport value in the shared one.

Usage:
    py mlb_game_results.py derive
    py mlb_game_results.py derive --season 2026
"""

import os
import sys
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn

SOURCE_TABLE = "mlb_game_log"
SPORT = "mlb"


def init_table():
    """Same table wnba_game_results.py creates. team_game_results was
    only ever built in the old Turso database (2026-07-11, pre-Postgres
    migration) and never existed in Supabase — AUTOINCREMENT is
    SQLite-only syntax and fails immediately against Postgres, even
    inside IF NOT EXISTS (Postgres parses the full statement before
    checking existence). Branches on backend, same pattern as other
    Postgres-vs-SQLite fixes already made across this codebase."""
    from database import SUPABASE_DB_URL
    conn = get_conn()
    c = conn.cursor()

    if SUPABASE_DB_URL:
        c.execute("""
            CREATE TABLE IF NOT EXISTS team_game_results (
                id          SERIAL PRIMARY KEY,
                sport       TEXT NOT NULL,
                date        TEXT NOT NULL,
                home_team   TEXT NOT NULL,
                away_team   TEXT NOT NULL,
                home_score  REAL NOT NULL,
                away_score  REAL NOT NULL,
                winner      TEXT NOT NULL,
                source      TEXT DEFAULT 'derived_from_game_log',
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sport, date, home_team, away_team)
            )
        """)
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS team_game_results (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                sport       TEXT NOT NULL,
                date        TEXT NOT NULL,
                home_team   TEXT NOT NULL,
                away_team   TEXT NOT NULL,
                home_score  REAL NOT NULL,
                away_score  REAL NOT NULL,
                winner      TEXT NOT NULL,
                source      TEXT DEFAULT 'derived_from_game_log',
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(sport, date, home_team, away_team)
            )
        """)
    conn.commit()
    conn.close()


def _normalize_date(raw_date: str) -> str:
    """Same normalization as wnba_game_results.py — mlb_game_log may
    store dates as YYYYMMDD; convert to YYYY-MM-DD to match every
    other table's date format."""
    raw_date = str(raw_date)
    if len(raw_date) == 8 and raw_date.isdigit():
        return f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    return raw_date


def derive_team_games_from_player_log(season: str = None) -> dict:
    """Reads mlb_game_log, groups player rows into per-team-per-game
    run totals, pairs both sides of each game, and upserts into
    team_game_results. Same skip-and-report philosophy as the WNBA
    version — never guesses a missing side or a tie."""
    init_table()

    conn = get_conn()
    c = conn.cursor()

    where = ""
    params = []
    if season:
        where = "WHERE date LIKE ?"
        params.append(f"{season}%")

    c.execute(f"""
        SELECT date, team_name, opponent, home_away, SUM(runs) AS team_score, COUNT(*) AS player_count
        FROM {SOURCE_TABLE}
        {where}
        GROUP BY date, team_name, opponent, home_away
    """, params)
    rows = [dict(r) for r in c.fetchall()]

    # Key each side by (date, frozenset of the two team names) — same
    # pairing approach as WNBA. KNOWN GAP: a doubleheader produces two
    # rows per team for the same key, so the second game's GROUP BY
    # aggregate here would already be wrong upstream (summing across
    # both games) before this function even sees it. Counted below via
    # a simple heuristic (games where player_count looks roughly double
    # a normal game) rather than silently trusting the total.
    games = {}
    for r in rows:
        date = _normalize_date(r["date"])
        key = (date, frozenset([r["team_name"], r["opponent"]]))
        games.setdefault(key, {})[r["home_away"]] = {
            "team": r["team_name"],
            "score": r["team_score"],
            "player_count": r["player_count"],
        }

    inserted = 0
    updated = 0
    skipped_incomplete = 0
    skipped_tie = 0
    skipped_bad_home_away = 0
    doubleheader_suspect = 0

    for (date, _teams), sides in games.items():
        home = sides.get("home")
        away = sides.get("away")

        if not home or not away:
            skipped_incomplete += 1
            continue
        if home["team"] == away["team"]:
            skipped_bad_home_away += 1
            continue
        if home["score"] == away["score"]:
            # MLB cannot end tied — this is a real data error (or a
            # doubleheader collision producing a coincidental equal
            # sum), not a valid game outcome. Skip and report.
            skipped_tie += 1
            continue

        # Heuristic doubleheader flag: a normal MLB team-game has
        # roughly 9-13 batters logged. Meaningfully more suggests two
        # games got summed into one key. Not a fix — just visibility,
        # per this file's stated doubleheader gap.
        if home["player_count"] > 16 or away["player_count"] > 16:
            doubleheader_suspect += 1

        winner = home["team"] if home["score"] > away["score"] else away["team"]

        c.execute("""
            INSERT INTO team_game_results (sport, date, home_team, away_team, home_score, away_score, winner)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(sport, date, home_team, away_team) DO UPDATE SET
                home_score = ?,
                away_score = ?,
                winner     = ?
        """, (
            SPORT, date, home["team"], away["team"], home["score"], away["score"], winner,
            home["score"], away["score"], winner,
        ))
        if c.rowcount == 1:
            inserted += 1
        else:
            updated += 1

    conn.commit()
    conn.close()

    summary = {
        "games_found": len(games),
        "inserted_or_updated": inserted + updated,
        "skipped_incomplete_one_side_missing": skipped_incomplete,
        "skipped_tie_derived_score": skipped_tie,
        "skipped_bad_home_away_data": skipped_bad_home_away,
        "doubleheader_suspect_not_fixed": doubleheader_suspect,
    }
    return summary


def get_team_games(team: str, sport: str = SPORT, date_range: tuple = None) -> list:
    """Same convenience reader as the WNBA version, sport defaults to mlb."""
    conn = get_conn()
    c = conn.cursor()
    where = "(home_team = ? OR away_team = ?) AND sport = ?"
    params = [team, team, sport]
    if date_range:
        where += " AND date BETWEEN ? AND ?"
        params.extend(date_range)
    c.execute(f"""
        SELECT date, home_team, away_team, home_score, away_score, winner
        FROM team_game_results
        WHERE {where}
        ORDER BY date DESC
    """, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def get_team_record(team: str, sport: str = SPORT, date_range: tuple = None) -> dict:
    """Real W-L record from team_game_results, no approximation."""
    games = get_team_games(team, sport=sport, date_range=date_range)

    if not games:
        return {
            "wins": 0,
            "losses": 0,
            "record": "0-0",
            "source": "team_game_results",
            "confidence": "low",
        }

    wins = sum(1 for g in games if g["winner"] == team)
    losses = len(games) - wins

    return {
        "wins": wins,
        "losses": losses,
        "record": f"{wins}-{losses}",
        "source": "team_game_results",
        "confidence": "high",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Derive MLB team-level game results from player box scores")
    parser.add_argument("cmd", choices=["derive"], help="derive: run the derivation and upsert team_game_results")
    parser.add_argument("--season", default=None, help="Optional season prefix filter, e.g. '2026'")
    args = parser.parse_args()

    if args.cmd == "derive":
        summary = derive_team_games_from_player_log(season=args.season)
        print("\n" + "=" * 60)
        print("  MLB team_game_results derivation")
        print("=" * 60)
        for k, v in summary.items():
            print(f"  {k}: {v}")
        print("=" * 60)
        if summary["skipped_incomplete_one_side_missing"]:
            print(f"\n  ⚠️  {summary['skipped_incomplete_one_side_missing']} game(s) skipped — only one team's")
            print("      box score was in mlb_game_log for that date. Not guessed, not filled in.")
        if summary["doubleheader_suspect_not_fixed"]:
            print(f"\n  ⚠️  {summary['doubleheader_suspect_not_fixed']} game(s) flagged as likely doubleheader")
            print("      collisions (>16 batters logged for one side) — these were still inserted")
            print("      but may have summed two games into one. Not fixed in this version.")