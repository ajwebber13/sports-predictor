"""
auto_predict_enhanced.py
=========================
Enhanced prediction runner — uses all available signals:
  - Multi-year historical stats (3 seasons)
  - EPA, success rate, pace, havoc
  - Weather, rest days, travel distance
  - Line movement (sharp money detection)
  - ATS historical record

Usage:
  python auto_predict_enhanced.py cfb 1
  python auto_predict_enhanced.py cfb 1 --top        (top games with real odds only)
  python auto_predict_enhanced.py cfb 1 --game lsu   (filter to specific team)

Note: First run takes longer (pulls 3 years of data + ATS lines).
      All data is cached for the session — subsequent games are instant.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import time
from datetime import datetime
from typing import Optional

# ─────────────────────────────────────────────────────────────
# API KEY — paste yours here
# ─────────────────────────────────────────────────────────────
CFBD_API_KEY = "KoCk3LFaEBTMMgXaJaJPoK7Ty5ypflsZ2/7QucNSupMoIOvANbBPcAv5YZQHRVVg"

# ─────────────────────────────────────────────────────────────
# SEASON CONFIG
# ─────────────────────────────────────────────────────────────
CFB_SCHEDULE_YEAR = 2026
CFB_STATS_YEAR    = 2025   # most recent completed season

# ─────────────────────────────────────────────────────────────
# MANUAL OVERRIDES
# ─────────────────────────────────────────────────────────────
MANUAL_ADJUSTMENTS = {
    # "Team Name": {"injury_adj": -0.10, "sos": 0.65}
}


def run_enhanced_cfb(
    week:       int,
    team_filter: Optional[str] = None,
    top_only:   bool = False,
    simulations: int = 10000,
):
    """
    Full enhanced CFB prediction pipeline.

    team_filter : if set, only show games involving this team name (case-insensitive)
    top_only    : if True, only show games with real Vegas odds
    """
    try:
        import cfbd
        from cfbd_api import CFBDClient
        from data_pipeline import (
            load_all_games, load_all_stats, load_advanced_stats,
            load_sp_ratings, load_elo_ratings, load_venues,
            build_enhanced_profile, build_game_context,
        )
        from enhanced_predictor import EnhancedPredictionEngine
        from roster_factors import build_roster_factors, load_returning_production, load_transfer_portal, load_qb_ratings
        from enhanced_display import print_roster_factors, print_confidence
        from enhanced_display import print_enhanced_prediction, print_enhanced_summary, export_enhanced_json
        from enhanced_data import GameContext
        from predictor import american_to_implied
    except ImportError as e:
        print(f"  ✗ Import failed: {e}")
        print("  Make sure all files are in C:\\temp\\sports_predictor\\")
        return

    # ── Connect ───────────────────────────────────────────────
    client = CFBDClient(api_key=CFBD_API_KEY)
    if not client.test_connection():
        print("  Check your API key in auto_predict_enhanced.py")
        return

    print(f"\n{'━'*66}")
    print(f"  ENHANCED CFB PREDICTIONS  |  Week {week}  |  {CFB_SCHEDULE_YEAR}")
    print(f"  Stats baseline: {CFB_STATS_YEAR}  |  3-year historical ATS")
    print(f"  Signals: EPA + Success Rate + Weather + Rest + Travel + Line Movement")
    print(f"{'━'*66}")

    # ── Pull schedule + lines ─────────────────────────────────
    print(f"\n  Pulling Week {week} schedule...")
    from cfbd_api import get_weekly_games
    games = get_weekly_games(client, CFB_SCHEDULE_YEAR, week)

    if not games:
        print("  No games found.")
        return

    # Apply filters
    if top_only:
        games = [g for g in games if g.get("has_odds")]
        print(f"  Filtered to {len(games)} games with real odds")
    if team_filter:
        tf = team_filter.lower()
        games = [g for g in games if tf in g["home_team"].lower() or tf in g["away_team"].lower()]
        print(f"  Filtered to games involving '{team_filter}'")

    # ── Pre-load all season data ──────────────────────────────
    print(f"\n  Pre-loading season data (this is cached after first run)...")
    print(f"  Loading {CFB_STATS_YEAR} season...")
    load_all_games(client, CFB_STATS_YEAR)
    load_all_stats(client, CFB_STATS_YEAR)
    load_advanced_stats(client, CFB_STATS_YEAR)
    load_sp_ratings(client, CFB_STATS_YEAR)
    load_elo_ratings(client, CFB_STATS_YEAR)

    # Load prior years for multi-year analysis
    for yr in [CFB_STATS_YEAR - 1, CFB_STATS_YEAR - 2]:
        print(f"  Loading {yr} season (historical)...")
        load_all_games(client, yr)
        load_advanced_stats(client, yr)

    venues = load_venues(client)

    # ── Pre-load roster factor data ───────────────────────────
    print(f"  Loading roster factors ({CFB_STATS_YEAR})...")
    load_returning_production(client, CFB_STATS_YEAR)
    load_transfer_portal(client, CFB_STATS_YEAR)
    load_qb_ratings(client, CFB_STATS_YEAR)

    # FBS team set
    from cfbd_api import load_season_stats as lss
    fbs_teams = set(lss(client, CFB_STATS_YEAR).keys())
    print(f"  ✓ FBS teams: {len(fbs_teams)}")

    # ── Build predictions ─────────────────────────────────────
    engine      = EnhancedPredictionEngine()
    predictions = []
    metas       = []

    print(f"\n  Building enhanced predictions for {len(games)} games...\n")

    for i, game in enumerate(games, 1):
        ht = game["home_team"]
        at = game["away_team"]
        print(f"  [{i}/{len(games)}] {at} @ {ht}")

        # Build enhanced profiles
        home_p = build_enhanced_profile(client, ht, CFB_STATS_YEAR, fbs_teams)
        away_p = build_enhanced_profile(client, at, CFB_STATS_YEAR, fbs_teams)

        # Build roster factors
        home_rf = build_roster_factors(client, ht, CFB_STATS_YEAR) if ht in fbs_teams else None
        away_rf = build_roster_factors(client, at, CFB_STATS_YEAR) if at in fbs_teams else None

        # Apply manual adjustments
        for team_p in [home_p, away_p]:
            overrides = MANUAL_ADJUSTMENTS.get(team_p.team_name, {})
            if "injury_adj" in overrides:
                team_p.injury_adj = overrides["injury_adj"]
            if "sos" in overrides:
                team_p.sos = overrides["sos"]

        # Build game context
        ctx = build_game_context(client, game, ht, at, CFB_SCHEDULE_YEAR, week, venues)

        # Predict
        pred = engine.predict(
            profile_a    = home_p,
            profile_b    = away_p,
            spread_line  = game["spread_line"],
            over_under   = game["over_under"],
            odds_a       = game["home_ml"],
            odds_b       = game["away_ml"],
            neutral_site = game["neutral"],
            a_is_home    = True,
            context      = ctx,
            simulations  = simulations,
            roster_a     = home_rf,
            roster_b     = away_rf,
        )
        predictions.append(pred)
        metas.append(game)

    # ── Display ───────────────────────────────────────────────
    print(f"\n{'═'*66}")
    print(f"  DETAILED REPORTS — CFB Week {week}")
    print(f"{'═'*66}")

    for pred, meta in zip(predictions, metas):
        odds_note = "" if meta.get("has_odds") else "  [No odds — defaults]"
        print(f"\n  {meta['away_team']} @ {meta['home_team']}{odds_note}")
        print_enhanced_prediction(pred)
        if home_rf: print_roster_factors(pred, pred.team_a_name, home_rf)
        if away_rf: print_roster_factors(pred, pred.team_b_name, away_rf)
        print_confidence(pred)

    # ── Summary ───────────────────────────────────────────────
    print_enhanced_summary(predictions)

    # ── Export ────────────────────────────────────────────────
    ts  = datetime.now().strftime("%Y%m%d_%H%M")
    out = f"enhanced_CFB_wk{week}_{ts}.json"
    export_enhanced_json(predictions, out)


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) < 2:
        print("""
Usage:
  python auto_predict_enhanced.py cfb 1              (all CFB Week 1 games)
  python auto_predict_enhanced.py cfb 1 --top        (only games with real odds)
  python auto_predict_enhanced.py cfb 1 --game lsu   (games involving LSU)
        """)
        sys.exit(0)

    league = args[0].upper()
    week   = int(args[1])
    top    = "--top" in args
    team   = None
    if "--game" in args:
        idx  = args.index("--game")
        team = args[idx + 1] if idx + 1 < len(args) else None

    if league == "CFB":
        run_enhanced_cfb(week, team_filter=team, top_only=top)
    else:
        print("NFL enhanced mode coming next. Run: python auto_predict_enhanced.py cfb [week]")
