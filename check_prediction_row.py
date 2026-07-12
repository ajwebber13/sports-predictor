"""
check_prediction_row.py - Culture & Pulse Analytics

Pulls every raw predictions row for a specific game today, to check
for a probability-flip bug (same class already found once in the
WNBA alert logic) or stale/duplicate rows being picked up by
get_model_projection()'s ORDER BY model_prob DESC LIMIT 1.

Read-only. Safe to run any time.

Usage:
    python check_prediction_row.py "Chicago Sky" "Dallas Wings" wnba
    python check_prediction_row.py "Chicago Sky" "Dallas Wings" wnba 2026-07-12
"""

import sys
from datetime import date
from database import get_conn


def run(team_a: str, team_b: str, sport: str, date_str: str = None):
    date_str = date_str or str(date.today())
    conn = get_conn()
    c = conn.cursor()

    print("=" * 70)
    print(f"  All predictions rows — {team_a} / {team_b} — {sport.upper()} — {date_str}")
    print("=" * 70)

    c.execute("""
        SELECT id, date, sport, game, home_team, away_team, bet, odds,
               model_prob, implied_prob, edge, predicted_winner, created_at
        FROM predictions
        WHERE date = ? AND sport = ?
          AND (
                (home_team LIKE ? AND away_team LIKE ?)
             OR (home_team LIKE ? AND away_team LIKE ?)
          )
        ORDER BY created_at ASC
    """, (date_str, sport, f"%{team_a}%", f"%{team_b}%", f"%{team_b}%", f"%{team_a}%"))
    rows = c.fetchall()

    if not rows:
        print("  No predictions rows found for this matchup/date.")
        print("  (get_model_projection() would have found nothing either —")
        print("   check if the game string or date format doesn't match what you expect.)")
    else:
        for r in rows:
            d = dict(r)
            print(f"\n  id={d['id']}  created_at={d['created_at']}")
            print(f"    game:            {d['game']}")
            print(f"    home_team:       {d['home_team']}")
            print(f"    away_team:       {d['away_team']}")
            print(f"    bet:             {d['bet']}")
            print(f"    predicted_winner:{d['predicted_winner']}")
            print(f"    model_prob:      {d['model_prob']}")
            print(f"    implied_prob:    {d['implied_prob']}")
            print(f"    edge:            {d['edge']}")
            print(f"    odds:            {d['odds']}")

            # Internal-consistency check: does bet/predicted_winner
            # actually match the team model_prob is describing?
            if d['bet'] and d['predicted_winner'] and d['bet'] != d['predicted_winner']:
                print(f"    ⚠️  MISMATCH: bet ('{d['bet']}') != predicted_winner ('{d['predicted_winner']}')")

        if len(rows) > 1:
            print(f"\n  ⚠️  {len(rows)} rows found for the same game/date — get_model_projection()'s")
            print(f"      ORDER BY model_prob DESC LIMIT 1 will silently pick whichever has the")
            print(f"      highest model_prob, which may not be the most recent/correct one.")

    conn.close()
    print()
    print("=" * 70)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print('Usage: python check_prediction_row.py "Team A" "Team B" sport [date]')
        sys.exit(1)
    team_a, team_b, sport = sys.argv[1], sys.argv[2], sys.argv[3]
    date_str = sys.argv[4] if len(sys.argv) > 4 else None
    run(team_a, team_b, sport, date_str)
