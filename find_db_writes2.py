import os

root = r"C:\temp\sports_predictor"
search_term = "predictions"

for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
    for filename in filenames:
        if filename.endswith(".py") and filename not in ("find_db_writes.py", "find_db_writes2.py"):
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if "INSERT" in line and "predictions" in line:
                            print(f"{filepath} — line {i}: {line.strip()}")
            except:
                pass