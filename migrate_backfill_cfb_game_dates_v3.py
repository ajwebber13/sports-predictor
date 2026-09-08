"""
migrate_backfill_cfb_game_dates_v3.py — Culture & Pulse Analytics
===================================================================
Same approach as migrate_backfill_cfb_game_dates_v2.py, extended to 5
more real CFB games: the ones auto_results.py's match_game() had been
silently unable to grade AT ALL until the 2026-09-08 team-name
normalization fix (Hawai'i's apostrophe, San Jose State's accent,
Miami (OH)'s parens, and Louisiana Monroe's "UL Monroe" alias — see
auto_results.py's _normalize_team_name()/TEAM_NAME_ALIASES). Because
these 5 games had zero `results` rows until that grading fix ran, v2's
audit (which queried `results` for games with >1 distinct date) could
not have found them — they were invisible to it by construction.

Once grading caught up, the same daily-re-predict pattern v2 fixed for
24 other CFB games showed up here too: each of these 5 real games had
been logged (and, once gradable, graded) once per day in the run-up to
kickoff, each day's row/result stamped with that day's own date. 18
results rows for 5 real games.

Resolution method: identical to v2 — ESPN's HOME team schedule fetched
by team ID, matched to the AWAY team by ID (not by display name, so
this can't trip over the exact name-formatting bug that got these
games here in the first place), hand-verified this session, converted
to a Central-time calendar date (CENTRAL_OFFSET=-5).

Corrects both predictions.game_date and results.date, same reasoning
as v2: results.date was already written (frozen) at grading time from
the wrong predictions.game_date, so predictions alone wouldn't move
the season record.

Usage:
    python migrate_backfill_cfb_game_dates_v3.py            # dry run
    python migrate_backfill_cfb_game_dates_v3.py --yes      # apply
"""

import argparse
import sys

sys.path.insert(0, ".")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn

# Hand-verified against ESPN's team-schedule endpoint this session
# (2026-09-08), by home-team ESPN ID -> opponent ESPN ID match — same
# method as v2's RESOLVED_CFB_GAME_DATES.
RESOLVED_CFB_GAME_DATES = {
    "Hawaii @ Stanford":                    "2026-08-29",
    "UNLV @ Hawaii":                        "2026-09-05",
    "San Jose State @ Eastern Michigan":    "2026-09-04",
    "Louisiana Monroe @ Mississippi State": "2026-09-05",
    "Miami OH @ Pittsburgh":                "2026-09-05",
}


def run(skip_confirm: bool = False):
    conn = get_conn()
    c = conn.cursor()

    print(f"Resolving {len(RESOLVED_CFB_GAME_DATES)} CFB game(s):\n")
    plan = []
    for game, correct_date in RESOLVED_CFB_GAME_DATES.items():
        c.execute(
            "SELECT id, game_date FROM predictions WHERE sport='cfb' AND game=?",
            (game,),
        )
        pred_rows = [dict(r) for r in c.fetchall()]
        c.execute(
            "SELECT id, date FROM results WHERE sport='cfb' AND game=?",
            (game,),
        )
        result_rows = [dict(r) for r in c.fetchall()]

        pred_wrong = [r for r in pred_rows if r["game_date"] != correct_date]
        result_wrong = [r for r in result_rows if r["date"] != correct_date]

        print(f"  {game}")
        print(f"    -> game_date={correct_date}: "
              f"{len(pred_wrong)}/{len(pred_rows)} predictions row(s) to fix, "
              f"{len(result_wrong)}/{len(result_rows)} results row(s) to fix")

        plan.append((game, correct_date, len(pred_wrong), len(result_wrong)))

    total_pred = sum(p[2] for p in plan)
    total_result = sum(p[3] for p in plan)
    print(f"\nTotal: {total_pred} predictions row(s), {total_result} results row(s) across "
          f"{len(plan)} game(s).")

    if not skip_confirm:
        answer = input("\nApply these changes? Type YES to proceed: ").strip()
        if answer != "YES":
            print("Cancelled — nothing changed.")
            conn.close()
            return

    for game, correct_date in RESOLVED_CFB_GAME_DATES.items():
        c.execute(
            "UPDATE predictions SET game_date = ? WHERE sport='cfb' AND game = ?",
            (correct_date, game),
        )
        c.execute(
            "UPDATE results SET date = ? WHERE sport='cfb' AND game = ?",
            (correct_date, game),
        )
    conn.commit()
    conn.close()
    print(f"\nDone. Updated predictions.game_date and results.date for "
          f"{len(RESOLVED_CFB_GAME_DATES)} game(s).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    run(skip_confirm=args.yes)
