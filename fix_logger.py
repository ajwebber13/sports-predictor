"""
Run this to fix prediction_logger.py:
  python fix_logger.py
"""
import os

fix = '''
if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 4 and sys.argv[1] == "update":
        game_name     = sys.argv[2]
        date_str      = sys.argv[3]
        actual_winner = sys.argv[4] if len(sys.argv) >= 5 else ""
        success = update_result(game_name, date_str, actual_winner)
        if success:
            print("Result saved. Run evaluate.py to see accuracy.")
        sys.exit(0)

    pending = list_pending_results()
    if not pending:
        print("No pending results to fill in.")
    else:
        print(f"\\n{len(pending)} predictions need results:\\n")
        for p in pending:
            print(f"  {p['date']} | {p['game']} | Bet: {p['bet']} | Predicted: {p['prediction']['predicted_winner']}")
        print("\\nTo update a result, run:")
        print('  python prediction_logger.py update "Game Name" "2026-06-04" "Actual Winner"')
'''

path = 'prediction_logger.py'
content = open(path).read()

# Find the if __name__ block and replace it
idx = content.find('if __name__ == "__main__":')
if idx == -1:
    print("ERROR: Could not find main block")
else:
    content = content[:idx] + fix
    with open(path, 'w') as f:
        f.write(content)
    print("Fixed! Testing...")
    import subprocess
    result = subprocess.run(['python', path, 'update', 'test', '2026-01-01', 'test'], capture_output=True, text=True)
    print(result.stdout)
    print(result.stderr)
