"""
update_todays_wnba_picks.py — one-time manual correction for 2026-07-15

Logs the 3 real WNBA games with the picks Drew confirmed:
  - Storm @ Sky:      Chicago Sky (unchanged — game already completed
                       at 11 AM, before today's injury/line-movement
                       fixes existed; using the REAL numbers from that
                       morning's Telegram alert, not a rewritten
                       after-the-fact number)
  - Sparks @ Lynx:    Minnesota Lynx (CORRECTED — original alert
                       picked Sparks before injury weighting existed;
                       today's fix flips this to Lynx, confirmed via
                       repeated reruns; logged as an explicit override
                       with a note, using REAL captured market odds
                       from odds_history — never a guessed number)
  - Valkyries @ Fever: Indiana Fever (unchanged — matches original alert)

Run once. Re-running is safe (log_prediction's dedupe/upsert means a
second run just re-writes the same row, doesn't duplicate).
"""

from database import get_conn, log_prediction


def get_real_odds(sport: str, home_team: str, away_team: str, date: str = None):
    """Pulls REAL captured odds from odds_history — never invents a
    number. Returns (home_ml, away_ml) or (None, None) if no row
    exists yet for this matchup today."""
    from datetime import datetime
    date = date or datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT home_ml, away_ml FROM odds_history
        WHERE date = ? AND sport = ? AND home_team = ? AND away_team = ?
    """, (date, sport, home_team, away_team))
    row = c.fetchone()
    conn.close()
    if not row:
        return None, None
    return row["home_ml"], row["away_ml"]


# ── Game 1: Storm @ Sky — unchanged, real morning alert numbers ──
log_prediction({
    "game": "Seattle Storm @ Chicago Sky",
    "bet": "Chicago Sky",
    "odds": -162,
    "model_prob": 74.3,
    "implied_prob": 61.8,   # -162 implies ~61.8%
    "edge": 74.3 - 61.8,
    "home_record": "7-16",
    "away_record": "6-19",
    "home_rest": 3,
    "away_rest": 3,
    "home_injuries": "Cardoso (Day-To-Day), Diggins (Out), Carrington (Out), Jackson (Out)",
    "away_injuries": "Mair (Out), Magbegor (Out)",
}, sport="wnba")
print("Logged: Storm @ Sky -> Chicago Sky (unchanged, pre-fix alert numbers)")

# ── Game 2: Sparks @ Lynx — CORRECTED, real captured odds ──
home_ml, away_ml = get_real_odds("wnba", "Minnesota Lynx", "Los Angeles Sparks")
if home_ml is None:
    print("\n⚠️  No real captured odds found for Lynx in odds_history yet.")
    print("    NOT logging with a guessed number — that's the exact fabricated-odds")
    print("    bug this project already found and fixed once. Run log_odds('wnba', ...)")
    print("    for today first (part of the normal morning run), or check odds_history")
    print("    manually before logging this pick.")
else:
    lynx_implied = round(abs(home_ml) / (abs(home_ml) + 100) * 100, 1) if home_ml < 0 else round(100 / (home_ml + 100) * 100, 1)
    log_prediction({
        "game": "Los Angeles Sparks @ Minnesota Lynx",
        "bet": "Minnesota Lynx",
        "odds": home_ml,
        "model_prob": 77.8,   # from today's corrected rerun
        "implied_prob": lynx_implied,
        "edge": round(77.8 - lynx_implied, 1),
        "home_record": "18-6",
        "away_record": "10-12",
        "home_rest": 3,
        "away_rest": 3,
        "home_injuries": "Juhasz (Day-To-Day)",
        "away_injuries": "Brink (Out), Plum (Out)",
    }, sport="wnba")
    print(f"Logged: Sparks @ Lynx -> Minnesota Lynx (CORRECTED override, real odds {home_ml})")

# ── Game 3: Valkyries @ Fever — unchanged, real morning alert numbers ──
log_prediction({
    "game": "Golden State Valkyries @ Indiana Fever",
    "bet": "Indiana Fever",
    "odds": -125,
    "model_prob": 81.7,
    "implied_prob": 55.6,   # -125 implies ~55.6%
    "edge": 81.7 - 55.6,
    "home_record": "14-9",
    "away_record": "17-7",
    "home_rest": 3,
    "away_rest": 5,
    "home_injuries": "Clark (Day-To-Day)",
    "away_injuries": "Williams (Day-To-Day), Rupert (Out)",
}, sport="wnba")
print("Logged: Valkyries @ Fever -> Indiana Fever (unchanged, pre-fix alert numbers)")
