"""
backtest_engine.py — Culture & Pulse Analytics
================================================
True walk-forward backtester. Runs the prediction model against
historical head_to_head data with zero future data leakage.

How it works:
  1. Pulls completed games from head_to_head chronologically
  2. For each game, derives team strength from elo_history (dated)
  3. Runs Monte Carlo simulation (same as live model)
  4. Blends Elo win probability
  5. Applies home/away split adjustment
  6. Records predicted winner vs actual winner
  7. Calculates ROI using -110 juice assumption

Usage:
  python backtest_engine.py              # backtest all sports
  python backtest_engine.py wnba         # WNBA only
  python backtest_engine.py nba          # NBA only
  python backtest_engine.py wnba 2025    # specific season
  python backtest_engine.py wnba --min-edge 0.08
  python backtest_engine.py wnba --min-prob 0.65
"""

import os
import sys
import json
import numpy as np
from datetime import datetime
from collections import defaultdict


# ─────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────

LEAGUE_CONSTANTS = {
    "nba":          {"league_avg_pts": 113.0, "home_adv_pts": 3.0, "score_std_dev": 11.0},
    "wnba":         {"league_avg_pts":  82.0, "home_adv_pts": 3.0, "score_std_dev": 10.0},
    "nfl":          {"league_avg_pts":  24.0, "home_adv_pts": 2.5, "score_std_dev":  8.0},
    "ncaaf":        {"league_avg_pts":  28.0, "home_adv_pts": 3.5, "score_std_dev":  9.0},
    "ncaab":        {"league_avg_pts":  72.0, "home_adv_pts": 3.5, "score_std_dev": 10.0},
    "hbcu_football":{"league_avg_pts":  24.0, "home_adv_pts": 3.0, "score_std_dev":  9.0},
    "hbcu_mbb":     {"league_avg_pts":  72.0, "home_adv_pts": 3.5, "score_std_dev": 10.0},
    "hbcu_wbb":     {"league_avg_pts":  65.0, "home_adv_pts": 3.0, "score_std_dev": 10.0},
}

DEFAULT_CONSTANTS = {"league_avg_pts": 80.0, "home_adv_pts": 3.0, "score_std_dev": 10.0}
SIMS = 5000


# ─────────────────────────────────────────────────────────────
# DB HELPER
# ─────────────────────────────────────────────────────────────

def get_conn():
    from database import get_conn as _gc
    return _gc()


def implied_prob_from_odds(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


# ─────────────────────────────────────────────────────────────
# WALK-FORWARD RATING SOURCES
# ─────────────────────────────────────────────────────────────

def get_elo_asof(team: str, sport: str, before_date: str) -> float:
    """
    Returns Elo rating just before game date using elo_history.
    This is the primary walk-forward safe rating source.
    Falls back to elo_ratings table (current) if no history found.
    Default 1500 if team has no Elo data at all.
    """
    conn = get_conn()
    c    = conn.cursor()

    # elo_history has dated records — fully walk-forward safe
    c.execute("""
        SELECT home_elo_after, away_elo_after, home_team, away_team
        FROM elo_history
        WHERE sport = ? AND date < ?
        AND (home_team = ? OR away_team = ?)
        ORDER BY date DESC LIMIT 1
    """, (sport, before_date, team, team))
    row = c.fetchone()
    conn.close()

    if row:
        if row["home_team"] == team:
            return float(row["home_elo_after"])
        return float(row["away_elo_after"])

    # Fall back to current elo_ratings (not walk-forward but better than nothing)
    conn = get_conn()
    c    = conn.cursor()
    c.execute("SELECT elo FROM elo_ratings WHERE sport = ? AND team_name = ?", (sport, team))
    row = c.fetchone()
    conn.close()
    return float(row["elo"]) if row else 1500.0


def elo_to_net_rating(elo: float) -> float:
    """Convert Elo to approximate net rating. 1500 Elo = 0.0 net rating."""
    return round((elo - 1500) / 25, 2)


def get_split_asof(team: str, sport: str) -> dict:
    """Pull home/away split from DB."""
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT home_avg_margin, away_avg_margin, home_away_gap,
               home_games, away_games
        FROM home_away_splits
        WHERE sport = ? AND team_name = ?
    """, (sport, team))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}


# ─────────────────────────────────────────────────────────────
# SIMULATION ENGINE
# ─────────────────────────────────────────────────────────────

def elo_win_prob(home_elo: float, away_elo: float, home_adv: float = 50.0) -> float:
    """Standard Elo win probability formula with home advantage."""
    return 1 / (1 + 10 ** (-(home_elo - away_elo + home_adv) / 400))


def simulate(home_net: float, away_net: float, constants: dict) -> tuple:
    """Monte Carlo simulation. Returns (home_win_prob, away_win_prob)."""
    c        = constants
    home_pts = c["league_avg_pts"] + home_net + c["home_adv_pts"]
    away_pts = c["league_avg_pts"] + away_net
    h        = np.random.normal(home_pts, c["score_std_dev"], SIMS)
    a        = np.random.normal(away_pts, c["score_std_dev"], SIMS)
    hp       = float(np.sum(h > a) / SIMS)
    return round(hp, 3), round(1 - hp, 3)


def predict_game(home_team: str, away_team: str, sport: str, date: str) -> dict:
    """
    Full walk-forward prediction for one game.
    Uses only data available before the game date.
    """
    constants = LEAGUE_CONSTANTS.get(sport.lower(), DEFAULT_CONSTANTS)

    # Elo ratings as of game date (walk-forward safe)
    home_elo = get_elo_asof(home_team, sport, date)
    away_elo = get_elo_asof(away_team, sport, date)

    # Convert Elo to net ratings for simulation
    home_net = elo_to_net_rating(home_elo)
    away_net = elo_to_net_rating(away_elo)

    # Monte Carlo simulation
    home_prob, away_prob = simulate(home_net, away_net, constants)

    # Elo win probability blend (70% Monte Carlo, 30% Elo)
    elo_home  = elo_win_prob(home_elo, away_elo)
    home_prob = round((home_prob * 0.7) + (elo_home * 0.3), 3)
    away_prob = round(1 - home_prob, 3)

    # Home/away split adjustment (only if 15+ games per split)
    try:
        home_split = get_split_asof(home_team, sport)
        if (home_split.get("home_games", 0) >= 15 and
                home_split.get("away_games", 0) >= 15):
            gap     = home_split["home_away_gap"]
            sample  = min(home_split["home_games"], home_split["away_games"])
            weight  = min(1.0, sample / 30)
            adj     = gap * 0.5 * weight * 0.01
            home_prob = round(min(max(home_prob + adj, 0.01), 0.99), 3)
            away_prob = round(1 - home_prob, 3)
    except Exception:
        pass

    # Edge calculation vs -110 implied
    implied_home = implied_prob_from_odds(-110)
    implied_away = 1 - implied_home
    home_edge    = home_prob - implied_home
    away_edge    = away_prob - implied_away

    if home_edge >= away_edge:
        pick, pick_prob, pick_edge = home_team, home_prob, home_edge
    else:
        pick, pick_prob, pick_edge = away_team, away_prob, away_edge

    return {
        "home_team": home_team,
        "away_team": away_team,
        "pick":      pick,
        "pick_prob": pick_prob,
        "pick_edge": round(pick_edge, 4),
        "home_prob": home_prob,
        "away_prob": away_prob,
        "home_elo":  round(home_elo, 1),
        "away_elo":  round(away_elo, 1),
    }


# ─────────────────────────────────────────────────────────────
# METRICS
# ─────────────────────────────────────────────────────────────

def calc_roi(records: list) -> dict:
    if not records:
        return {"total": 0, "wins": 0, "losses": 0,
                "win_pct": 0, "net_units": 0, "roi_pct": 0}
    total  = len(records)
    wins   = sum(1 for r in records if r["correct"])
    losses = total - wins
    net    = sum((100 / 110) if r["correct"] else -1.0 for r in records)
    return {
        "total":     total,
        "wins":      wins,
        "losses":    losses,
        "win_pct":   round(wins / total * 100, 1),
        "net_units": round(net, 2),
        "roi_pct":   round(net / total * 100, 1),
    }


def edge_tier(edge: float) -> str:
    if edge >= 0.10:  return "★★★ STRONG  (10%+)"
    if edge >= 0.05:  return "★★ MODERATE (5-10%)"
    return "★ SLIGHT    (<5%)"


def confidence_tier(prob: float) -> str:
    if prob >= 0.70:  return "70%+"
    if prob >= 0.60:  return "60-69%"
    return "<60%"


# ─────────────────────────────────────────────────────────────
# BACKTEST RUNNER
# ─────────────────────────────────────────────────────────────

def run_backtest(sport=None, season=None, min_edge=0.0,
                 min_prob=0.0, verbose=False):

    conn = get_conn()
    c    = conn.cursor()

    query  = """SELECT * FROM head_to_head
                WHERE home_score IS NOT NULL
                AND away_score IS NOT NULL
                AND winner IS NOT NULL"""
    params = []

    if sport:
        query += " AND sport = ?"
        params.append(sport.lower())
    if season:
        query += " AND season = ?"
        params.append(season)

    query += " ORDER BY date ASC"
    c.execute(query, params)
    games = c.fetchall()
    conn.close()

    if not games:
        print(f"\n  No historical games found.")
        return

    print(f"\n{'═'*60}")
    print(f"  🔬 WALK-FORWARD BACKTEST  |  Culture & Pulse Analytics")
    print(f"  Sport: {sport.upper() if sport else 'ALL'}  |  Games in DB: {len(games)}")
    if min_edge > 0:
        print(f"  Filter: Edge >= {min_edge*100:.0f}%")
    if min_prob > 0:
        print(f"  Filter: Confidence >= {min_prob*100:.0f}%")
    print(f"  Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    print(f"{'═'*60}")
    print(f"\n  Running {len(games)} games...\n")

    results = []
    skipped = 0
    errors  = 0

    for i, game in enumerate(games):
        home_team = game["home_team"]
        away_team = game["away_team"]
        date      = game["date"]
        sport_key = game["sport"].lower()
        actual    = game["winner"]

        if not actual or not home_team or not away_team:
            skipped += 1
            continue

        try:
            pred = predict_game(home_team, away_team, sport_key, date)

            # Apply filters
            if pred["pick_prob"] < min_prob:
                skipped += 1
                continue
            if pred["pick_edge"] < min_edge:
                skipped += 1
                continue

            correct = (pred["pick"].lower() in actual.lower() or
                      actual.lower() in pred["pick"].lower())

            results.append({
                "date":      date,
                "sport":     sport_key,
                "season":    game["season"],
                "home_team": home_team,
                "away_team": away_team,
                "pick":      pred["pick"],
                "pick_prob": pred["pick_prob"],
                "pick_edge": pred["pick_edge"],
                "home_elo":  pred["home_elo"],
                "away_elo":  pred["away_elo"],
                "actual":    actual,
                "correct":   correct,
                "game_type": game["game_type"] if game["game_type"] else "regular_season",
            })

            if verbose and i % 200 == 0:
                print(f"  {i}/{len(games)} processed...")

        except Exception as e:
            errors += 1
            if verbose:
                print(f"  Error {home_team} vs {away_team} ({date}): {e}")
            continue

    if not results:
        print(f"  No predictions generated.")
        print(f"  Skipped: {skipped}  Errors: {errors}")
        print(f"\n  Likely cause: No elo_history data for this sport.")
        print(f"  Run: python elo_ratings.py to check Elo coverage.")
        return

    # ── REPORT ───────────────────────────────────────────────

    overall = calc_roi(results)
    sign    = "+" if overall["net_units"] >= 0 else ""

    print(f"  OVERALL")
    print(f"  {'─'*40}")
    print(f"  Record:    {overall['wins']}W - {overall['losses']}L  ({overall['win_pct']}%)")
    print(f"  ROI:       {sign}{overall['roi_pct']}%  ({sign}{overall['net_units']} units)")
    print(f"  Games:     {overall['total']}  |  Skipped: {skipped}  |  Errors: {errors}")

    # By sport
    sports = sorted(set(r["sport"] for r in results))
    if len(sports) > 1:
        print(f"\n  BY SPORT")
        print(f"  {'─'*40}")
        for s in sports:
            sr   = [r for r in results if r["sport"] == s]
            m    = calc_roi(sr)
            sign = "+" if m["net_units"] >= 0 else ""
            print(f"  {s.upper():<14}  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u  {sign}{m['roi_pct']}% ROI")

    # By season
    seasons = sorted(set(r["season"] for r in results if r["season"]))
    if len(seasons) > 1:
        print(f"\n  BY SEASON (last 5)")
        print(f"  {'─'*40}")
        for s in seasons[-5:]:
            sr   = [r for r in results if r["season"] == s]
            m    = calc_roi(sr)
            sign = "+" if m["net_units"] >= 0 else ""
            print(f"  {s:<8}  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u  {sign}{m['roi_pct']}% ROI")

    # By edge tier
    print(f"\n  BY EDGE TIER")
    print(f"  {'─'*40}")
    for tier in ["★★★ STRONG  (10%+)", "★★ MODERATE (5-10%)", "★ SLIGHT    (<5%)"]:
        tr = [r for r in results if edge_tier(r["pick_edge"]) == tier]
        if not tr:
            continue
        m    = calc_roi(tr)
        sign = "+" if m["net_units"] >= 0 else ""
        print(f"  {tier}:  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u  {sign}{m['roi_pct']}% ROI")

    # By confidence
    print(f"\n  BY CONFIDENCE")
    print(f"  {'─'*40}")
    for tier in ["70%+", "60-69%", "<60%"]:
        cr = [r for r in results if confidence_tier(r["pick_prob"]) == tier]
        if not cr:
            continue
        m    = calc_roi(cr)
        sign = "+" if m["net_units"] >= 0 else ""
        print(f"  {tier}:  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u  {sign}{m['roi_pct']}% ROI")

    # Home vs away picks
    home_picks = [r for r in results if r["pick"] == r["home_team"]]
    away_picks = [r for r in results if r["pick"] == r["away_team"]]
    print(f"\n  HOME vs AWAY PICKS")
    print(f"  {'─'*40}")
    if home_picks:
        m    = calc_roi(home_picks)
        sign = "+" if m["net_units"] >= 0 else ""
        print(f"  Home picks:  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u")
    if away_picks:
        m    = calc_roi(away_picks)
        sign = "+" if m["net_units"] >= 0 else ""
        print(f"  Away picks:  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u")

    # Game type
    reg     = [r for r in results if r.get("game_type") == "regular_season"]
    playoff = [r for r in results if r.get("game_type") == "playoff"]
    if reg and playoff:
        print(f"\n  BY GAME TYPE")
        print(f"  {'─'*40}")
        for label, subset in [("Regular", reg), ("Playoff", playoff)]:
            m    = calc_roi(subset)
            sign = "+" if m["net_units"] >= 0 else ""
            print(f"  {label:<10}  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u")

    # Walk-forward rolling windows
    print(f"\n  WALK-FORWARD ROLLING WINDOWS")
    print(f"  {'─'*40}")
    window_size = 50 if len(results) >= 100 else 10
    step        = max(5, window_size // 5)
    if len(results) >= window_size:
        for i in range(0, len(results) - window_size + 1, step):
            window = results[i:i+window_size]
            m      = calc_roi(window)
            dates  = f"{window[0]['date']} → {window[-1]['date']}"
            sign   = "+" if m["net_units"] >= 0 else ""
            print(f"  {dates}:  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u")
    else:
        print(f"  Need {window_size}+ games. Have {len(results)}.")

    # Verdict
    roi = overall["roi_pct"]
    wp  = overall["win_pct"]
    sign = "+" if roi >= 0 else ""
    print(f"\n  VERDICT")
    print(f"  {'─'*40}")
    if roi > 5 and wp > 54:
        print(f"  ✅ Model shows positive edge: {sign}{roi}% ROI across {overall['total']} games")
        print(f"     Elo-based predictions have real predictive value.")
    elif roi > 0:
        print(f"  ⚠️  Model is marginally profitable ({sign}{roi}% ROI)")
        print(f"     Small edge — monitor closely and raise confidence threshold.")
    else:
        print(f"  ❌ No edge detected at this scale ({sign}{roi}% ROI)")
        print(f"     Consider raising min confidence or edge thresholds.")

    # High edge only summary
    strong = [r for r in results if r["pick_edge"] >= 0.10]
    if strong and len(strong) >= 10:
        sm    = calc_roi(strong)
        ssign = "+" if sm["net_units"] >= 0 else ""
        print(f"\n  ★ HIGH EDGE ONLY (10%+): {sm['wins']}W-{sm['losses']}L "
              f"({sm['win_pct']}%)  |  {ssign}{sm['net_units']}u  {ssign}{sm['roi_pct']}% ROI")
        if sm["roi_pct"] > overall["roi_pct"]:
            print(f"     → Filtering to strong edges improves ROI significantly.")

    print(f"\n{'═'*60}\n")

    # Save results
    out = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"backtest_results_{sport or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    )
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved: {os.path.basename(out)}\n")
    return results


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("sport",      nargs="?", default=None)
    parser.add_argument("season",     nargs="?", default=None)
    parser.add_argument("--min-edge", type=float, default=0.0)
    parser.add_argument("--min-prob", type=float, default=0.0)
    parser.add_argument("--verbose",  action="store_true")
    args = parser.parse_args()

    run_backtest(
        sport    = args.sport,
        season   = args.season,
        min_edge = args.min_edge,
        min_prob = args.min_prob,
        verbose  = args.verbose,
    )
