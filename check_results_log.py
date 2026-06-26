import json

with open("results_log.json", "r") as f:
    data = json.load(f)

for entry in data:
    print(entry)