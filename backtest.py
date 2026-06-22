"""
backtest.py — Culture & Pulse Analytics
=========================================
Walk-forward backtester. Evaluates historical predictions from
data/predictions/ with no future data leakage.

Metrics:
  - Win rate, ROI, units P&L by sport / version / edge tier
  - Calibration check (does 70% confidence actually win 70%?)
  - Confidence tier separation (are strong picks beating weak picks?)
  - WNBA-specific breakdown

Usage:
  python backtest.py              # full backtest report
  python backtest.py wnba         # WNBA only
  python backtest.py v3           # current model only
  python backtest.py calibration  # calibration report only
"""

import os
import sys
import json
import glob
from datetime import datetime
from collections import defaultdict


# ─────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────

BASE_DIR        = os.path.dirname(__file__)
PREDICTIONS_DIR = os.path.join(BASE_DIR, "data", "predictions")
RESULTS_LOG     = os.path.join(BASE_DIR, "results_log.json")

VERSION_DATES = {
    "v1": ("2026-01-01", "2026-06-09"),
    "v2": ("2026-06-10", "2026-06-18"),
    "v3": ("2026-06-19", "9999-12-31"),
}


# ─────────────────────────────────────────────────────────────
# LOADERS
# ─────────────────────────────────────────────────────────────

def infer_version(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        for ver, (start, end) in VERSION_DATES.items():
            s = datetime.strptime(start, "%Y-%m-%d").date()
            e = datetime.strptime(end,   "%Y-%m-%d").date()
            if s <= d <= e:
                return ver
    except Exception:
        pass
    return "v1"


def load_completed_predictions() -> list:
    """
    Load all prediction JSONs that have actual results filled in.
    Skips pending/future games. Returns list of enriched dicts.
    """
    pattern = os.path.join(PREDICTIONS_DIR, "*.json")
    files   = sorted(glob.glob(pattern))
    records = []

    for filepath in files:
        try:
            with open(filepath) as f:
                pred = json.load(f)
        except Exception:
            continue

        actual_winner = pred.get("actual_result", {}).get("actual_winner", "")
        if not actual_winner:
            continue  # skip pending

        game      = pred.get("game", "")
        bet_label = pred.get("bet", "")
        date_str  = pred.get("date", "")
        sport     = pred.get("sport", "").upper()
        edge      = float(pred.get("edge", 0))
        model_prob = float(pred.get("model_prob", 50))
        odds_raw  = pred.get("odds", "N/A")
        version   = pred.get("model_version") or infer_version(date_str)

        # Determine predicted winner
        parts     = game.split(" @ ")
        away_team = parts[0] if len(parts) == 2 else ""
        home_team = parts[1] if len(parts) == 2 else ""
        bet_on_home = home_team in bet_label
        predicted = home_team if bet_on_home else away_team

        won = (
            predicted.lower() in actual_winner.lower() or
            actual_winner.lower() in predicted.lower()
        )

        # Parse American odds to decimal payout
        payout = _parse_odds(odds_raw)

        records.append({
            "game":        game,
            "sport":       sport,
            "date":        date_str,
            "version":     version,
            "bet":         bet_label,
            "odds":        odds_raw,
            "payout":      payout,      # profit per 1 unit staked if win
            "edge":        edge,
            "model_prob":  model_prob,
            "predicted":   predicted,
            "actual":      actual_winner,
            "won":         won,
        })

    # Sort chronologically — critical for walk-forward integrity
    records.sort(key=lambda r: r["date"])
    return records


def _parse_odds(odds_str) -> float:
    """American odds → profit per 1 unit staked. Default -110."""
    try:
        odds = int(str(odds_str).replace(" ", ""))
        if odds > 0:
            return odds / 100.0
        else:
            return 100.0 / abs(odds)
    except Exception:
        return 100 / 110  # -110 default


# ─────────────────────────────────────────────────────────────
# METRICS
# ─────────────────────────────────────────────────────────────

def calc_metrics(records: list) -> dict:
    if not records:
        return {}

    total  = len(records)
    wins   = sum(1 for r in records if r["won"])
    losses = total - wins
    win_pct = wins / total * 100 if total else 0

    net_units = sum(r["payout"] if r["won"] else -1.0 for r in records)
    roi_pct   = net_units / total * 100 if total else 0

    # Longest win/loss streak
    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    for r in records:
        if r["won"]:
            cur_win += 1
            cur_loss = 0
        else:
            cur_loss += 1
            cur_win  = 0
        max_win_streak  = max(max_win_streak,  cur_win)
        max_loss_streak = max(max_loss_streak, cur_loss)

    return {
        "total":            total,
        "wins":             wins,
        "losses":           losses,
        "win_pct":          round(win_pct,  1),
        "net_units":        round(net_units, 2),
        "roi_pct":          round(roi_pct,  1),
        "max_win_streak":   max_win_streak,
        "max_loss_streak":  max_loss_streak,
    }


def edge_tier(edge: float) -> str:
    if edge >= 8:
        return "★★★ STRONG  (8%+)"
    elif edge >= 5:
        return "★★ MODERATE (5-8%)"
    else:
        return "★ SLIGHT    (<5%)"


def confidence_tier(prob: float) -> str:
    if prob >= 70:
        return "70%+"
    elif prob >= 60:
        return "60-69%"
    else:
        return "<60%"


# ─────────────────────────────────────────────────────────────
# CALIBRATION
# ─────────────────────────────────────────────────────────────

def calibration_report(records: list):
    """
    Check if model confidence scores match actual win rates.
    A well-calibrated model: 70% confidence → ~70% actual win rate.
    """
    if not records:
        return

    buckets = defaultdict(list)
    for r in records:
        prob = r["model_prob"]
        # Bucket into 10% bands
        band = int(prob // 10) * 10
        band = max(50, min(band, 90))  # clip to 50-90
        buckets[band].append(r)

    print(f"\n  CALIBRATION CHECK")
    print(f"  {'─'*50}")
    print(f"  {'Confidence':12}  {'Games':>6}  {'Actual Win%':>11}  {'Gap':>8}  {'Status':>10}")
    print(f"  {'─'*50}")

    well_calibrated = True
    for band in sorted(buckets.keys()):
        group    = buckets[band]
        actual   = sum(1 for r in group if r["won"]) / len(group) * 100
        expected = band + 5  # midpoint of band
        gap      = actual - expected
        status   = "✅ OK" if abs(gap) <= 10 else "⚠️  OFF"
        if abs(gap) > 10:
            well_calibrated = False
        print(f"  {band}-{band+9}%       {len(group):>6}  {actual:>10.1f}%  {gap:>+7.1f}%  {status:>10}")

    print(f"  {'─'*50}")
    if well_calibrated:
        print(f"  ✅ Model is reasonably calibrated")
    else:
        print(f"  ⚠️  Model confidence scores need recalibration")
        print(f"     Confidence is drifting from actual results.")
        print(f"     Consider Platt scaling or isotonic regression.")


# ─────────────────────────────────────────────────────────────
# WNBA DIAGNOSIS
# ─────────────────────────────────────────────────────────────

def wnba_diagnosis(records: list):
    """
    Deep dive into WNBA performance to find where the model breaks.
    Splits by: home vs away pick, edge tier, confidence, win streak.
    """
    wnba = [r for r in records if r["sport"] == "WNBA"]
    if not wnba:
        print("\n  No WNBA records found.")
        return

    print(f"\n{'═'*60}")
    print(f"  🏀 WNBA MODEL DIAGNOSIS")
    print(f"{'═'*60}")

    # Overall
    m = calc_metrics(wnba)
    sign = "+" if m["net_units"] >= 0 else ""
    print(f"\n  Overall:  {m['wins']}W-{m['losses']}L ({m['win_pct']}%)  |  {sign}{m['net_units']}u  {sign}{m['roi_pct']}% ROI")
    print(f"  Streaks:  Max Win {m['max_win_streak']} | Max Loss {m['max_loss_streak']}")

    # By model version
    print(f"\n  BY VERSION")
    print(f"  {'─'*40}")
    for ver in ["v1", "v2", "v3"]:
        vr = [r for r in wnba if r["version"] == ver]
        if not vr:
            continue
        vm   = calc_metrics(vr)
        sign = "+" if vm["net_units"] >= 0 else ""
        print(f"  {ver}:  {vm['wins']}W-{vm['losses']}L ({vm['win_pct']}%)  |  {sign}{vm['net_units']}u  {sign}{vm['roi_pct']}% ROI")

    # Home vs away picks
    home_picks = [r for r in wnba if r["game"].split(" @ ")[-1].strip() in r["bet"]]
    away_picks = [r for r in wnba if r not in home_picks]

    print(f"\n  HOME vs AWAY PICKS")
    print(f"  {'─'*40}")
    if home_picks:
        hm   = calc_metrics(home_picks)
        sign = "+" if hm["net_units"] >= 0 else ""
        print(f"  Home picks:  {hm['wins']}W-{hm['losses']}L ({hm['win_pct']}%)  |  {sign}{hm['net_units']}u")
    if away_picks:
        am   = calc_metrics(away_picks)
        sign = "+" if am["net_units"] >= 0 else ""
        print(f"  Away picks:  {am['wins']}W-{am['losses']}L ({am['win_pct']}%)  |  {sign}{am['net_units']}u")

    # By edge tier
    print(f"\n  BY EDGE TIER")
    print(f"  {'─'*40}")
    for tier_label in ["★★★ STRONG  (8%+)", "★★ MODERATE (5-8%)", "★ SLIGHT    (<5%)"]:
        tr = [r for r in wnba if edge_tier(r["edge"]) == tier_label]
        if not tr:
            continue
        tm   = calc_metrics(tr)
        sign = "+" if tm["net_units"] >= 0 else ""
        print(f"  {tier_label}:  {tm['wins']}W-{tm['losses']}L ({tm['win_pct']}%)  |  {sign}{tm['net_units']}u")

    # By confidence bucket
    print(f"\n  BY CONFIDENCE")
    print(f"  {'─'*40}")
    for bucket in ["70%+", "60-69%", "<60%"]:
        cr = [r for r in wnba if confidence_tier(r["model_prob"]) == bucket]
        if not cr:
            continue
        cm   = calc_metrics(cr)
        sign = "+" if cm["net_units"] >= 0 else ""
        print(f"  {bucket}:  {cm['wins']}W-{cm['losses']}L ({cm['win_pct']}%)  |  {sign}{cm['net_units']}u")

    # Walk-forward — rolling 10-game window
    print(f"\n  ROLLING 10-GAME WINDOW (chronological)")
    print(f"  {'─'*40}")
    if len(wnba) >= 10:
        for i in range(0, len(wnba) - 9, 5):
            window = wnba[i:i+10]
            wm     = calc_metrics(window)
            dates  = f"{window[0]['date']} → {window[-1]['date']}"
            sign   = "+" if wm["net_units"] >= 0 else ""
            print(f"  {dates}:  {wm['wins']}W-{wm['losses']}L ({wm['win_pct']}%)  |  {sign}{wm['net_units']}u")
    else:
        print(f"  Need 10+ games for rolling window. Have {len(wnba)}.")

    # Verdict
    print(f"\n  DIAGNOSIS SUMMARY")
    print(f"  {'─'*40}")
    issues = []

    v2_wnba = [r for r in wnba if r["version"] == "v2"]
    if v2_wnba:
        v2m = calc_metrics(v2_wnba)
        if v2m["win_pct"] < 52:
            issues.append(f"  ❌ v2 WNBA win rate ({v2m['win_pct']}%) is below breakeven — layers added in v2 hurt performance")

    if home_picks and away_picks:
        hm = calc_metrics(home_picks)
        am = calc_metrics(away_picks)
        if abs(hm["win_pct"] - am["win_pct"]) > 15:
            issues.append(f"  ⚠️  Home picks ({hm['win_pct']}%) vs Away picks ({am['win_pct']}%) gap is large — home/away weighting may be off")

    strong = [r for r in wnba if r["edge"] >= 8]
    slight = [r for r in wnba if r["edge"] < 5]
    if strong and slight:
        sm = calc_metrics(strong)
        wm = calc_metrics(slight)
        if sm["win_pct"] - wm["win_pct"] < 5:
            issues.append(f"  ⚠️  Strong edge picks ({sm['win_pct']}%) barely outperform weak picks ({wm['win_pct']}%) — edge scoring not differentiating")

    if not issues:
        print(f"  ✅ No critical issues detected in WNBA model")
    else:
        for issue in issues:
            print(issue)


# ─────────────────────────────────────────────────────────────
# FULL BACKTEST REPORT
# ─────────────────────────────────────────────────────────────

def full_report(records: list, filter_sport: str = None, filter_version: str = None):
    if filter_sport:
        records = [r for r in records if r["sport"] == filter_sport.upper()]
    if filter_version:
        records = [r for r in records if r["version"] == filter_version.lower()]

    if not records:
        print("\n  No completed predictions found matching filter.")
        return

    print(f"\n{'═'*60}")
    print(f"  📊 BACKTEST REPORT  |  Culture & Pulse Analytics")
    print(f"  Generated: {datetime.now().strftime('%B %d, %Y %I:%M %p')}")
    if filter_sport:
        print(f"  Filter: {filter_sport.upper()} only")
    if filter_version:
        print(f"  Filter: {filter_version.upper()} only")
    print(f"{'═'*60}")

    # Overall
    m    = calc_metrics(records)
    sign = "+" if m["net_units"] >= 0 else ""
    print(f"\n  OVERALL")
    print(f"  {'─'*40}")
    print(f"  Record:      {m['wins']}W - {m['losses']}L  ({m['win_pct']}%)")
    print(f"  ROI:         {sign}{m['roi_pct']}%  ({sign}{m['net_units']} units)")
    print(f"  Games:       {m['total']}")
    print(f"  Win Streak:  {m['max_win_streak']}  |  Loss Streak: {m['max_loss_streak']}")

    # By version
    versions = sorted(set(r["version"] for r in records))
    if len(versions) > 1:
        print(f"\n  BY MODEL VERSION")
        print(f"  {'─'*40}")
        for ver in ["v1", "v2", "v3"]:
            vr = [r for r in records if r["version"] == ver]
            if not vr:
                continue
            vm   = calc_metrics(vr)
            sign = "+" if vm["net_units"] >= 0 else ""
            label = {"v1": "[retired]", "v2": "[retired]", "v3": "[current]"}.get(ver, "")
            print(f"  {ver} {label:<10}  {vm['wins']}W-{vm['losses']}L ({vm['win_pct']}%)  |  {sign}{vm['net_units']}u  {sign}{vm['roi_pct']}% ROI")

    # By sport
    sports = sorted(set(r["sport"] for r in records))
    if len(sports) > 1:
        print(f"\n  BY SPORT")
        print(f"  {'─'*40}")
        for sport in sports:
            sr   = [r for r in records if r["sport"] == sport]
            sm   = calc_metrics(sr)
            sign = "+" if sm["net_units"] >= 0 else ""
            print(f"  {sport:<6}  {sm['wins']}W-{sm['losses']}L ({sm['win_pct']}%)  |  {sign}{sm['net_units']}u  {sign}{sm['roi_pct']}% ROI")

    # By edge tier
    print(f"\n  BY EDGE TIER")
    print(f"  {'─'*40}")
    for tier_label in ["★★★ STRONG  (8%+)", "★★ MODERATE (5-8%)", "★ SLIGHT    (<5%)"]:
        tr = [r for r in records if edge_tier(r["edge"]) == tier_label]
        if not tr:
            continue
        tm   = calc_metrics(tr)
        sign = "+" if tm["net_units"] >= 0 else ""
        print(f"  {tier_label}:  {tm['wins']}W-{tm['losses']}L ({tm['win_pct']}%)  |  {sign}{tm['net_units']}u  {sign}{tm['roi_pct']}% ROI")

    # Calibration
    calibration_report(records)

    # Walk-forward rolling window
    print(f"\n  WALK-FORWARD (rolling 10-game window)")
    print(f"  {'─'*40}")
    if len(records) >= 10:
        for i in range(0, len(records) - 9, 5):
            window = records[i:i+10]
            wm     = calc_metrics(window)
            dates  = f"{window[0]['date']} → {window[-1]['date']}"
            sign   = "+" if wm["net_units"] >= 0 else ""
            print(f"  {dates}:  {wm['wins']}W-{wm['losses']}L ({wm['win_pct']}%)  |  {sign}{wm['net_units']}u")
    else:
        print(f"  Need 10+ completed games. Have {len(records)}.")

    print(f"\n{'═'*60}\n")


# ─────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    records = load_completed_predictions()

    if not records:
        print("\n  No completed predictions found in data/predictions/")
        print("  Run results_tracker.py first to pull ESPN results.")
        sys.exit(0)

    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "full"

    if cmd == "wnba":
        wnba_diagnosis(records)

    elif cmd == "calibration":
        print(f"\n{'═'*60}")
        print(f"  🎯 CALIBRATION REPORT  |  Culture & Pulse Analytics")
        print(f"{'═'*60}")
        calibration_report(records)
        print()

    elif cmd in ("v1", "v2", "v3"):
        full_report(records, filter_version=cmd)

    elif cmd in ("nba", "nfl", "ncaaf", "ncaab", "ncaaw"):
        full_report(records, filter_sport=cmd)

    else:
        # Full report + WNBA diagnosis
        full_report(records)
        wnba_diagnosis(records)
