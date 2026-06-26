import os

search_term = "INSERT INTO predictions"
root = r"C:\temp\sports_predictor"

for dirpath, dirnames, filenames in os.walk(root):
    # Skip hidden and cache folders
    dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
    for filename in filenames:
        if filename.endswith(".py"):
            filepath = os.path.join(dirpath, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    contents = f.read()
                    if search_term in contents:
                        print(f"Found in: {filepath}")
            except:
                pass