"""
import_json.py — Culture & Pulse Analytics
Imports existing JSON prediction files into cp_analytics.db
Run once to backfill your pick history.
"""

import json
import os
from database import get_conn, init_db

PREDICTIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "predictions")


def import_json_files():
    init_db()
    conn    = get_conn()
    c       = conn.cursor()
    imported = 0
    skipped  = 0
    results  = 0

    # Walk all subdirectories too
    all_files = []
    for root, dirs, files in os.walk(PREDICTIONS_DIR):
        for f in files:
            if f.endswith(".json") and f != ".gitkeep":
                all_files.append(os.path.join(root, f))

    print(f"\nFound {len(all_files)} JSON files to import...")

    for filepath in sorted(all_files):
        try:
            with open(filepath) as f:
                data = json.load(f)

            game    = data.get("game", "")
            sport   = data.get("sport", "")
            date    = data.get("date", "")
            bet     = data.get("bet", "")
            odds    = data.get("odds")
            if odds == "N/A":
                odds = None

            model_prob   = data.get("model_prob", 0)
            implied_prob = data.get("implied_prob", 0)
            edge         = data.get("edge", 0)

            predicted_winner = data.get("prediction", {}).get("predicted_winner", "")
            actual_winner    = data.get("actual_result", {}).get("actual_winner", "")

            # Parse teams from game string
            parts     = game.split(" @ ")
            away_team = parts[0] if len(parts) == 2 else ""
            home_team = parts[1] if len(parts) == 2 else ""

            if not game or not sport or not date:
                skipped += 1
                continue

            # Insert into predictions table
            c.execute("""
                INSERT OR IGNORE INTO predictions
                (date, sport, game, home_team, away_team,
                 bet, odds, model_prob, implied_prob, edge,
                 predicted_winner)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (date, sport, game, home_team, away_team,
                  bet, odds, model_prob, implied_prob, edge,
                  predicted_winner))

            pred_id = c.lastrowid
            imported += 1

            # If we have an actual result log it to results table
            if actual_winner:
                is_correct = 1 if predicted_winner == actual_winner else 0

                # Try to get home/away scores from filename — not available
                # Just log winner and correctness
                c.execute("""
                    INSERT OR IGNORE INTO results
                    (date, sport, game, home_team, away_team,
                     actual_winner, prediction_id, correct,
                     edge_at_pick, odds_at_pick)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (date, sport, game, home_team, away_team,
                      actual_winner, pred_id, is_correct,
                      edge, odds))

                status = "✅" if is_correct else "❌"
                print(f"  {status} {date} | {sport.upper()} | {game} → {actual_winner}")
                results += 1

        except Exception as e:
            print(f"  Error importing {filepath}: {e}")
            skipped += 1

    conn.commit()
    conn.close()

    print(f"\n{'='*50}")
    print(f"Import complete.")
    print(f"Predictions imported: {imported}")
    print(f"Results logged:       {results}")
    print(f"Skipped:              {skipped}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    import_json_files()

    # Show model report after import
    from model_report import print_report
    print_report()