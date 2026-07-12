"""
nba_game_results.py — Culture & Pulse Analytics
====================================================
Derives team-level game results from nba_game_log's player-level box
scores. Same pattern as wnba_game_results.py — see that file's
docstring for the full rationale (results is a betting ledger, not a
season log; this derives the real games-truth-layer table instead).

nba_game_log covers a COMPLETE finished season (2025-10-21 through
2026-06-13, confirmed via check_game_log_coverage_v2.py) — NBA is in
its offseason as of this run (2026-07), so this represents "who was
actually best last season," not a live current-season ranking. That's
still a legitimate, useful validation dataset — just set that
expectation before anyone reads an NBA Power Ranking and assumes it's
current.

DIFFERENCE FROM WNBA: nba_game_log has 33 distinct team_name values
for a 30-team league — almost certainly All-Star/exhibition entries.
WNBA's derivation didn't need an exhibition filter (came back clean at
exactly 15 real teams); this one does. Reuses the same
is_exhibition_team() already proven in elo_ratings.py rather than
writing a second copy of that logic.

Usage:
    py nba_game_results.py derive
    py nba_game_results.py derive --season 2025
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from elo_ratings import is_exhibition_team

SOURCE_TABLE = "nba_game_log"
SPORT = "nba"


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
    raw_date = str(raw_date)
    if len(raw_date) == 8 and raw_date.isdigit():
        return f"{raw_date[0:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
    return raw_date


def derive_team_games_from_player_log(season: str = None) -> dict:
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

    games = {}
    skipped_exhibition_rows = 0
    for r in rows:
        if is_exhibition_team(r["team_name"]) or is_exhibition_team(r["opponent"]):
            skipped_exhibition_rows += 1
            continue
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

    return {
        "games_found": len(games),
        "inserted_or_updated": inserted + updated,
        "skipped_exhibition_rows_before_pairing": skipped_exhibition_rows,
        "skipped_incomplete_one_side_missing": skipped_incomplete,
        "skipped_tie_derived_score": skipped_tie,
        "skipped_bad_home_away_data": skipped_bad_home_away,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Derive NBA team-level game results from player box scores")
    parser.add_argument("cmd", choices=["derive"])
    parser.add_argument("--season", default=None, help="Optional season prefix filter, e.g. '2025'")
    args = parser.parse_args()

    if args.cmd == "derive":
        summary = derive_team_games_from_player_log(season=args.season)
        print("\n" + "=" * 60)
        print("  NBA team_game_results derivation")
        print("=" * 60)
        for k, v in summary.items():
            print(f"  {k}: {v}")
        print("=" * 60)
