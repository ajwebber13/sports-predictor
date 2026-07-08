"""
wipe_player_props.py — Culture & Pulse Analytics
==================================================
Clears out the player_props table so the dashboard starts fresh with
only new star-player + projection-based picks going forward.

This does NOT touch: predictions, results, team_stats, odds_history,
or any game-outcome data — only player_props.

Run this yourself (not from any automated pipeline) since it needs
your real Turso credentials to hit production. Uses the same
database.py connection everything else uses — if TURSO_DATABASE_URL /
TURSO_AUTH_TOKEN are set, this wipes production. If not, it wipes your
local cp_analytics.db instead.

Usage:
    python wipe_player_props.py            # shows row count, asks to confirm
    python wipe_player_props.py --yes      # skips the confirmation prompt
"""

import argparse
import sys

sys.path.insert(0, ".")
from database import get_conn


def wipe(skip_confirm: bool = False):
    conn = get_conn()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) as n FROM player_props")
    count = dict(c.fetchone())["n"]

    if count == 0:
        print("player_props is already empty — nothing to wipe.")
        conn.close()
        return

    print(f"\n  player_props currently has {count} rows.")
    print("  This will permanently delete ALL of them (not predictions/results — just props).\n")

    if not skip_confirm:
        answer = input("  Type WIPE to confirm: ").strip()
        if answer != "WIPE":
            print("  Cancelled — nothing deleted.")
            conn.close()
            return

    c.execute("DELETE FROM player_props")
    conn.commit()
    conn.close()
    print(f"  Done. {count} rows deleted from player_props.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()
    wipe(skip_confirm=args.yes)
