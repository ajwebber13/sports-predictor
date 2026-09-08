"""
migrate_backfill_cfb_game_dates_v2.py — Culture & Pulse Analytics
===================================================================
Follow-up to migrate_add_game_date.py, which explicitly scoped itself
to 4 hand-verified rows and called a broader historical crawl "its own,
separately-scoped effort." This is that effort.

2026-09-08 audit found 24 CFB (sport, game) matchups whose predictions
were re-logged daily in the run-up to kickoff — each day's row (and,
after grading, each corresponding results row) stamped with THAT DAY's
own date as game_date/date, because these all predate the 2026-09-04
game_date-resolution fix (or logged in the narrow window after the
column existed but before the resolution path was reliably wired in).
Textbook case: NC State @ Virginia logged identically 7 days running
(2026-08-23 through 2026-08-29), each graded correct=1 independently —
one real win counted 7 times in the season record.

Resolution method: for each affected game, fetch the HOME team's real
ESPN schedule by team ID (site.api.espn.com .../teams/{id}/schedule)
and find the event whose opponent ID matches the away team — the same
ID-based approach cfb_data.get_cfb_events() already uses elsewhere in
this codebase specifically to avoid ESPN displayName mismatches (see
the Hawaii/Hawai'i apostrophe bug found the same session). Every one
of the 24 resolved to exactly one unambiguous match — hand-verified
against ESPN this session, then converted to a Central-time calendar
date at CENTRAL_OFFSET=-5, matching raw_time_to_central_date()'s own
convention elsewhere in this codebase. Three of these (Tulane @ Duke,
Oklahoma State @ Tulsa, Boston College @ Cincinnati) independently
reproduce the exact 2026-09-05 dates migrate_add_game_date.py already
hand-verified — cross-check that this method agrees with the known-good
prior fix before trusting it on the other 21.

Corrects BOTH tables, since results.date was already written (frozen)
at grading time from the wrong predictions.game_date — fixing
predictions alone would leave the season record (which reads from
results, not predictions) unchanged:
  1. predictions.game_date -> the real date, for every row sharing
     that (sport, game) regardless of which day it was logged.
  2. results.date -> the same real date, for every already-graded row
     for that (sport, game).

Usage:
    python migrate_backfill_cfb_game_dates_v2.py            # dry run
    python migrate_backfill_cfb_game_dates_v2.py --yes      # apply
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
# (2026-09-08), by home-team ESPN ID -> opponent ESPN ID match (see
# module docstring). game -> correct game_date.
RESOLVED_CFB_GAME_DATES = {
    "North Carolina @ TCU":               "2026-08-29",
    "NC State @ Virginia":                "2026-08-29",
    "Memphis @ UNLV":                     "2026-08-29",
    "Colorado @ Georgia Tech":            "2026-09-03",
    "Akron @ Wake Forest":                "2026-09-03",
    "Miami @ Stanford":                   "2026-09-04",
    "Fresno State @ USC":                 "2026-09-04",
    "Coastal Carolina @ West Virginia":   "2026-09-05",
    "Florida Atlantic @ Florida":         "2026-09-05",
    "Wyoming @ Colorado State":           "2026-09-05",
    "Kent State @ South Carolina":        "2026-09-05",
    "Boston College @ Cincinnati":        "2026-09-05",
    "Boise State @ Oregon":               "2026-09-05",
    "Baylor @ Auburn":                    "2026-09-05",
    "Ball State @ Ohio State":            "2026-09-05",
    "Northern Illinois @ Iowa":           "2026-09-05",
    "Ohio @ Nebraska":                    "2026-09-05",
    "Oklahoma State @ Tulsa":             "2026-09-05",
    "Texas State @ Texas":                "2026-09-05",
    "Tulane @ Duke":                      "2026-09-05",
    "UCLA @ California":                  "2026-09-05",
    "Western Michigan @ Michigan":        "2026-09-05",
    "Clemson @ LSU":                      "2026-09-05",
    "Wisconsin @ Notre Dame":             "2026-09-06",
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
