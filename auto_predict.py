"""
auto_predict.py
================
Main prediction runner — auto pulls schedule, stats, and odds.

Usage:
  python auto_predict.py            # interactive menu
  python auto_predict.py nfl 1      # NFL Week 1
  python auto_predict.py cfb 3      # CFB Week 3
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from datetime import datetime
from enhanced_predictor import EnhancedPredictionEngine as PredictionEngine
from alert_engine import build_alert, PredictionInput  # ← Phase 1: Smarter Alerts

# ─────────────────────────────────────────────────────────────
# !! PASTE YOUR CFBD API KEY HERE !!
# Get a free key at: https://collegefootballdata.com/key
# ─────────────────────────────────────────────────────────────
CFBD_API_KEY = "KoCk3LFaEBTMMgXaJaJPoK7Ty5ypflsZ2/7QucNSupMoIOvANbBPcAv5YZQHRVVg"

# ─────────────────────────────────────────────────────────────
# SEASON CONFIG — update each season
# ─────────────────────────────────────────────────────────────

NFL_SCHEDULE_YEAR = 2026
NFL_STATS_YEAR    = 2025
NFL_SEASON_TYPE   = 2

CFB_SCHEDULE_YEAR = 2026
CFB_STATS_YEAR    = 2025
CFB_SEASON_TYPE   = 2


# ─────────────────────────────────────────────────────────────
# MANUAL ADJUSTMENTS (optional)
# ─────────────────────────────────────────────────────────────

MANUAL_ADJUSTMENTS = {
    # "Kansas City Chiefs": {"injury_adj": -0.10, "sos": 0.58},
}


def apply_overrides(matchups_with_meta: list) -> list:
    for matchup, meta in matchups_with_meta:
        for team in [matchup.team_a, matchup.team_b]:
            overrides = MANUAL_ADJUSTMENTS.get(team.name, {})
            if "injury_adj" in overrides:
                team.injury_adj = overrides["injury_adj"]
            if "sos" in overrides:
                team.sos = overrides["sos"]
    return matchups_with_meta


# ─────────────────────────────────────────────────────────────
# CFB RUNNER
# ─────────────────────────────────────────────────────────────

def run_cfb(week: int):
    from cfbd_api import CFBDClient, build_weekly_matchups

    client = CFBDClient(api_key=CFBD_API_KEY)

    if not client.test_connection():
        print("  Check your API key in auto_predict.py")
        return

    print(f"\n{'┌'*64}")
    print(f"  CFB WEEK {week}  |  Source: College Football Data API")
    print(f"  Schedule: {CFB_SCHEDULE_YEAR}  |  Stats: {CFB_STATS_YEAR}")
    if CFB_STATS_YEAR < CFB_SCHEDULE_YEAR:
        print(f"  ⚠   Preseason projection using {CFB_STATS_YEAR} stats.")
    print(f"{'└'*64}")

    matchups = build_weekly_matchups(
        client      = client,
        year        = CFB_SCHEDULE_YEAR,
        week        = week,
        stats_year  = CFB_STATS_YEAR,
        simulations = 10000,
    )

    if not matchups:
        print("  No matchups found.")
        return

    matchups = apply_overrides(matchups)
    _run_and_display("CFB", week, matchups)


# ─────────────────────────────────────────────────────────────
# NFL RUNNER
# ─────────────────────────────────────────────────────────────

def run_nfl(week: int, use_pbp: bool = False):
    try:
        from nfl_data_api import build_weekly_matchups, check_install
    except ImportError:
        print("  ✗ nfl_data_api.py not found.")
        return

    if not check_install():
        print("  Run: pip install nfl-data-py pandas")
        return

    print(f"\n{'┌'*64}")
    print(f"  NFL WEEK {week}  |  Source: nfl-data-py")
    print(f"  Schedule: {NFL_SCHEDULE_YEAR}  |  Stats: {NFL_STATS_YEAR}")
    print(f"{'└'*64}")

    matchups = build_weekly_matchups(
        schedule_year = NFL_SCHEDULE_YEAR,
        week          = week,
        stats_year    = NFL_STATS_YEAR,
        use_pbp       = use_pbp,
        simulations   = 10000,
    )

    if not matchups:
        print("  No matchups found.")
        return

    matchups = apply_overrides(matchups)
    _run_and_display("NFL", week, matchups)


# ─────────────────────────────────────────────────────────────
# DISPLAY + EXPORT
# ─────────────────────────────────────────────────────────────

def _run_and_display(league: str, week: int, matchups_with_meta: list):
    engine      = PredictionEngine()
    predictions = []
    metas       = []

    for matchup, meta in matchups_with_meta:
        pred = engine.predict(matchup)
        predictions.append(pred)
        metas.append(meta)

    print(f"\n{'═'*64}")

    for pred, meta in zip(predictions, metas):
        home = meta.get("home_team", pred.team_b_name)
        away = meta.get("away_team", pred.team_a_name)

        # ── Build upgraded alert slip ──────────────────────────
        try:
            alert_input = PredictionInput(
                sport            = league,
                home_team        = home,
                away_team        = away,
                game_time        = meta.get("game_time", "TBD"),
                home_win_prob    = getattr(pred, "team_b_win_prob", 0.5),
                away_win_prob    = getattr(pred, "team_a_win_prob", 0.5),
                bet_team         = getattr(pred, "predicted_winner", away),
                bet_type         = "ML",
                odds             = int(meta.get("odds", -110)),
                home_net_rating  = float(meta.get("home_net_rating", 0.0)),
                away_net_rating  = float(meta.get("away_net_rating", 0.0)),
                opening_odds     = meta.get("opening_odds", None),
                closing_odds     = meta.get("closing_odds", None),
                stake            = 100.0
            )
            alert = build_alert(alert_input)
            print(alert.formatted_slip)

        except Exception as e:
            # Fallback to original display if alert engine fails
            print(f"\n  {away} @ {home}")
            print(f"  [Fallback] {away} @ {home} — check alert_engine output above")
            print(f"  [Alert engine error: {e}]")

    print(f"\n  ✓ {len(predictions)} predictions complete.")

    ts  = datetime.now().strftime("%Y%m%d_%H%M")
    out = f"predictions_{league}_wk{week}_{ts}.json"
    # export_json disabled — no display module
    pass


# ─────────────────────────────────────────────────────────────
# INTERACTIVE MENU
# ─────────────────────────────────────────────────────────────

def run_interactive():
    print("""
┌──────────────────────────────────────────────────────────────
  SPORTS PREDICTION ENGINE  v2.0  |  Culture & Pulse Analytics
└──────────────────────────────────────────────────────────────

  Options:
    1  CFB — choose week
    2  NFL — choose week
    q  Quit
""")

    choice = input("  Choose: ").strip().lower()

    if choice == "q":
        return
    elif choice == "1":
        week = int(input("  CFB week (1–15): ").strip())
        run_cfb(week)
    elif choice == "2":
        week = int(input("  NFL week (1–18): ").strip())
        run_nfl(week)
    else:
        print("  Invalid choice.")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) == 3:
        league = sys.argv[1].upper()
        week   = int(sys.argv[2])
        if league == "CFB":
            run_cfb(week)
        elif league == "NFL":
            run_nfl(week)
        else:
            print("Usage: python auto_predict.py [nfl|cfb] [week]")
    else:
        run_interactive()
