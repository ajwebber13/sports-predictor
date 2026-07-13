"""
wnba_game_results.py — Culture & Pulse Analytics
====================================================
Derives team-level game results (one row per game: both teams, final
scores, winner) from wnba_game_log's player-level box scores. This is
the "games truth layer" that elo_ratings.py, strength_of_schedule.py,
and team_form_engine.py should read from instead of `results`.

Why this exists (found 2026-07-11): `results` is a betting ledger —
it only contains games where render_job.py's edge/win-prob filter
decided the model had a real opinion, then auto_results.py graded it.
That's the correct behavior for ROI/CLV/model-accuracy tracking, but
it means results only had 22 distinct WNBA game-dates when the real
season had ~55+ (confirmed via check_game_log_coverage.py).
wnba_game_log, by contrast, is populated independently of any
prediction — it's ESPN's real box scores for every game played,
whether or not the model ever looked at it. That's the right
foundation for "what actually happened this season."

`results` is NOT being touched or replaced by this — it keeps doing
exactly its job (picks, odds, CLV, ROI, win/loss on WAGERS). This file
only adds a second, independent table for the games themselves.

Method: wnba_game_log has no team-level score column (it's
per-player pts/reb/ast/stl/blk), so team score is derived as
SUM(pts) GROUP BY date, team_name, opponent, home_away. Each game
produces exactly two such grouped rows (one per team) that get paired
by (date, the two team names) into one team_game_results row.

Known gaps, not silently hidden:
  - If only one side of a game has box-score rows in wnba_game_log
    (the other team's players never got logged), that game is
    SKIPPED — never guessed or half-filled. Counted and reported.
  - A derived tie (same score both sides) is a data error in
    basketball — skipped and reported rather than picking a winner.
  - Team totals summed from box scores CAN differ slightly from the
    real final score if a role player got missed by the source
    ingestion. This is a known, accepted approximation — good enough
    for Elo/rankings, not for anything requiring exact final scores.

Schema (team_game_results — new table, does not touch `results`):
    id, sport, date, home_team, away_team, home_score, away_score,
    winner, source, created_at
    UNIQUE(sport, date, home_team, away_team) — safe to re-run the
    derivation; re-running updates rather than duplicates.

Only WNBA is wired up right now (that's what was audited). NBA/MLB
have their own similarly-shaped *_game_log tables per the existing
codebase pattern, but their exact column names haven't been verified
against this script — do NOT assume they match without checking
first, same lesson as the head_to_head investigation.

Usage:
    py wnba_game_results.py derive
    py wnba_game_results.py derive --season 2026
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn

SOURCE_TABLE = "wnba_game_log"
SPORT = "wnba"


def init_table():
    conn = get_conn()
    c = conn.cursor()
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
    """wnba_game_log stores YYYYMMDD (e.g. '20260710'). Normalize to
    YYYY-MM-DD to match the date format used everywhere else in the
    codebase (predictions, results) — mixing formats across tables
    would silently break any date_range filter that assumes hyphens."""
    raw_date = str(raw_date)
    if len(raw_date) == 8 and raw_date.isdigit():
        return f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    return raw_date  # already normalized, or unexpected format — pass through


def derive_team_games_from_player_log(season: str = None) -> dict:
    """Reads wnba_game_log, groups player rows into per-team-per-game
    totals, pairs both sides of each game, and upserts into
    team_game_results. Returns a summary dict of what happened —
    never silently drops a mismatch."""
    init_table()

    conn = get_conn()
    c = conn.cursor()

    where = ""
    params = []
    if season:
        where = "WHERE date LIKE ?"
        params.append(f"{season}%")

    c.execute(f"""
        SELECT date, team_name, opponent, home_away, SUM(pts) AS team_score, COUNT(*) AS player_count
        FROM {SOURCE_TABLE}
        {where}
        GROUP BY date, team_name, opponent, home_away
    """, params)
    rows = [dict(r) for r in c.fetchall()]

    # Key each side by (date, frozenset of the two team names) so both
    # sides of the same game pair up regardless of which one we see first.
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
            skipped_tie += 1
            continue

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
    }
    return summary


def get_team_games(team: str, sport: str = SPORT, date_range: tuple = None) -> list:
    """Convenience reader — same shape as querying `results` used to
    be, for anything that wants to read team_game_results directly
    without going through elo_ratings/team_form_engine."""
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
    """Real W-L record from team_game_results, no approximation.
    Returns confidence='low' only when there's zero data for the team
    yet (new expansion team, not-yet-derived date range) — never
    fabricates a record to fill the shape."""
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
    parser = argparse.ArgumentParser(description="Derive WNBA team-level game results from player box scores")
    parser.add_argument("cmd", choices=["derive"], help="derive: run the derivation and upsert team_game_results")
    parser.add_argument("--season", default=None, help="Optional season prefix filter, e.g. '2026'")
    args = parser.parse_args()

    if args.cmd == "derive":
        summary = derive_team_games_from_player_log(season=args.season)
        print("\n" + "=" * 60)
        print("  WNBA team_game_results derivation")
        print("=" * 60)
        for k, v in summary.items():
            print(f"  {k}: {v}")
        print("=" * 60)
        if summary["skipped_incomplete_one_side_missing"]:
            print(f"\n  ⚠️  {summary['skipped_incomplete_one_side_missing']} game(s) skipped — only one team's")
            print("      box score was in wnba_game_log for that date. Not guessed, not filled in.")
