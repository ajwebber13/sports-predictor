import os

root = r"C:\temp\sports_predictor"

for dirpath, dirnames, filenames in os.walk(root):
    dirnames[:] = [d for d in dirnames if not d.startswith('.') and d != '__pycache__']
    for filename in filenames:
        if "result" in filename.lower() and filename.endswith(".py"):
            print(os.path.join(dirpath, filename))