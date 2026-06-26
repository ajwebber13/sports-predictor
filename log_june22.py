from database import log_prediction, log_result

# Log the two edge picks from June 22
picks = [
    {
        "game":          "Toronto Tempo @ Atlanta Dream",
        "bet":           "Atlanta Dream ML",
        "odds":          -204,
        "model_prob":    69.5,
        "implied_prob":  52.4,
        "edge":          0.171,
        "home_record":   "11-4",
        "away_record":   "8-8",
        "home_rest":     2,
        "away_rest":     3,
        "home_injuries": "",
        "away_injuries": "Nyara Sabally (Out), Brittney Sykes (Out), Kiki Rice (Out)",
    },
    {
        "game":          "Dallas Wings @ Seattle Storm",
        "bet":           "Dallas Wings ML",
        "odds":          -202,
        "model_prob":    60.6,
        "implied_prob":  23.8,
        "edge":          0.156,
        "home_record":   "3-14",
        "away_record":   "10-6",
        "home_rest":     2,
        "away_rest":     2,
        "home_injuries": "Ezi Magbegor (Out), Jade Melbourne (Out), Taina Mair (Out), Jordan Horston (Out)",
        "away_injuries": "Odyssey Sims (Out), Alanna Smith (Out), Alysha Clark (Day-To-Day)",
    },
]

for pick in picks:
    log_prediction(pick, "wnba")
    print(f"Logged: {pick['game']}")

# Log results — both were wins
log_result("wnba", "Toronto Tempo @ Atlanta Dream", "2026-06-22", 0, 0)
log_result("wnba", "Dallas Wings @ Seattle Storm",  "2026-06-22", 0, 0)
print("Done — run auto_results.py 2026-06-22 to pull actual scores")