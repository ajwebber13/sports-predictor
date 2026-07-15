"""
capture_closing_lines.py — Culture & Pulse Analytics
=====================================================
Runs in the afternoon (before tip-off) to capture closing lines,
compute movement vs the morning opening, and flag sharp action.

Writes to:
  - odds_history.closing_home_ml / closing_away_ml
  - line_movement table (opening vs closing, movement size, sharp signal)

Schedule: run ~2 hrs before first tip (e.g. 4 PM CT for 6:30 PM games)
Render cron: wnba-afternoon already runs at 4 PM CT — this can be
             called from render_job.py or added as its own cron.

Usage:
    python capture_closing_lines.py            # all active sports
    python capture_closing_lines.py --sport wnba
    python capture_closing_lines.py --dry-run  # print without writing
"""

import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn

CENTRAL_OFFSET = -5  # CDT

ACTIVE_SPORTS = ["wnba", "nfl", "ncaaf"]  # nba added when in season

# Sharp movement threshold — line moves 8+ points = possible sharp money
SHARP_THRESHOLD = 8


def get_today_ct() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).strftime("%Y-%m-%d")


def american_to_implied(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def implied_shift(opening_ml: int, closing_ml: int) -> float:
    """How much did the implied probability shift? Positive = team got shorter (more favored)."""
    open_implied  = american_to_implied(opening_ml) * 100
    close_implied = american_to_implied(closing_ml) * 100
    return round(close_implied - open_implied, 1)


def movement_label(movement: int) -> str:
    if movement == 0:
        return "no movement"
    direction = "shorter" if movement < 0 else "longer"
    return f"moved {abs(movement)} pts {direction}"


def sharp_signal(home_move: int, away_move: int, home_team: str, away_team: str) -> str | None:
    """
    Detect sharp signal. Sharp money typically:
    - Moves the line against the public (public bets favorites, sharps fade them)
    - Creates meaningful line movement (8+ points on ML)
    """
    if abs(home_move) >= SHARP_THRESHOLD:
        direction = "shorter" if home_move < 0 else "longer"
        team = home_team
        return f"{team} ML moved {home_move:+d} pts ({direction}) — possible sharp action"
    if abs(away_move) >= SHARP_THRESHOLD:
        direction = "shorter" if away_move < 0 else "longer"
        team = away_team
        return f"{team} ML moved {away_move:+d} pts ({direction}) — possible sharp action"
    return None


def run(sports: list, dry_run: bool = False):
    from services.odds_parser import get_live_odds

    conn    = get_conn()
    c       = conn.cursor()
    today   = get_today_ct()

    print(f"\n{'='*55}")
    print(f"  Closing Line Capture — {today} {'[DRY RUN]' if dry_run else ''}")
    print(f"  Sports: {', '.join(s.upper() for s in sports)}")
    print(f"{'='*55}\n")

    for sport in sports:
        print(f"  Fetching current odds for {sport.upper()}...")
        games = get_live_odds(sport)
        print(f"  Got {len(games)} game(s)\n")

        for game in games:
            home_team = game.get("home_team", "")
            away_team = game.get("away_team", "")
            current_home_ml = None
            current_away_ml = None

            for bm in game.get("bookmakers", []):
                for market in bm.get("markets", []):
                    if market["key"] == "h2h":
                        for o in market.get("outcomes", []):
                            if o["name"] == home_team:
                                current_home_ml = o["price"]
                            elif o["name"] == away_team:
                                current_away_ml = o["price"]
                        if current_home_ml and current_away_ml:
                            break
                if current_home_ml and current_away_ml:
                    break

            if not current_home_ml or not current_away_ml:
                print(f"  ⚠️  No current odds: {away_team} @ {home_team}")
                continue

            # Pull opening line from this morning's odds_history
            c.execute("""
                SELECT opening_home_ml, opening_away_ml
                FROM odds_history
                WHERE date = ? AND sport = ?
                AND (home_team = ? OR LOWER(home_team) LIKE LOWER(?))
                AND (away_team = ? OR LOWER(away_team) LIKE LOWER(?))
                LIMIT 1
            """, (today, sport, home_team, f"%{home_team}%", away_team, f"%{away_team}%"))
            row = c.fetchone()

            if not row:
                print(f"  ⚠️  No opening line found: {away_team} @ {home_team} — was morning run completed?")
                continue

            opening_home = row["opening_home_ml"]
            opening_away = row["opening_away_ml"]

            if not opening_home or not opening_away:
                print(f"  ⚠️  Opening line is null: {away_team} @ {home_team}")
                continue

            movement_home = current_home_ml - opening_home
            movement_away = current_away_ml - opening_away
            home_shift    = implied_shift(opening_home, current_home_ml)
            away_shift    = implied_shift(opening_away, current_away_ml)
            sharp         = sharp_signal(movement_home, movement_away, home_team, away_team)

            print(f"  {away_team} @ {home_team}")
            print(f"    Home: {opening_home:+d} → {current_home_ml:+d} ({movement_label(movement_home)}, {home_shift:+.1f}% implied)")
            print(f"    Away: {opening_away:+d} → {current_away_ml:+d} ({movement_label(movement_away)}, {away_shift:+.1f}% implied)")
            if sharp:
                print(f"    🔔 {sharp}")
            print()

            if not dry_run:
                # Update odds_history closing lines
                c.execute("""
                    UPDATE odds_history
                    SET closing_home_ml = ?,
                        closing_away_ml = ?
                    WHERE date = ? AND sport = ?
                    AND (home_team = ? OR LOWER(home_team) LIKE LOWER(?))
                    AND (away_team = ? OR LOWER(away_team) LIKE LOWER(?))
                """, (current_home_ml, current_away_ml, today, sport,
                      home_team, f"%{home_team}%", away_team, f"%{away_team}%"))

                # Write to line_movement table
                c.execute("""
                    INSERT INTO line_movement
                    (date, sport, home_team, away_team,
                     opening_home_ml, opening_away_ml,
                     closing_home_ml, closing_away_ml,
                     movement_home, movement_away,
                     sharp_signal, captured_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (date, sport, home_team, away_team) DO UPDATE SET
                        opening_home_ml = EXCLUDED.opening_home_ml,
                        opening_away_ml = EXCLUDED.opening_away_ml,
                        closing_home_ml = EXCLUDED.closing_home_ml,
                        closing_away_ml = EXCLUDED.closing_away_ml,
                        movement_home   = EXCLUDED.movement_home,
                        movement_away   = EXCLUDED.movement_away,
                        sharp_signal    = EXCLUDED.sharp_signal,
                        captured_at     = EXCLUDED.captured_at
                """, (today, sport, home_team, away_team,
                      opening_home, opening_away,
                      current_home_ml, current_away_ml,
                      movement_home, movement_away,
                      sharp, datetime.now(timezone.utc).isoformat()))

    if not dry_run:
        conn.commit()
        print("  DB updated.")
    else:
        print("  [DRY RUN] No changes written.")

    conn.close()
    print(f"\n{'='*55}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", type=str, help="Single sport to run (default: all active)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sports = [args.sport] if args.sport else ACTIVE_SPORTS
    run(sports, dry_run=args.dry_run)
