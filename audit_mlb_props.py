"""
audit_mlb_props.py — Culture & Pulse Analytics
===============================================
Backtest the new price-aware / Wilson-adjusted prop filter (prop_edge.py)
against every MLB prop that has already been graded, and compare it to
the old 70/30 hit-rate rule on the same props.

Answers, with real numbers:
  1. Old rule (green & hit_rate>=70 over, hit_rate<=30 under): record, ROI
  2. New rule at several MIN_EDGE_PTS settings: record, ROI, pick count
  3. Same split by stat (hits / rbis / runs / hr / strikeouts ...)
  4. Data-quality flags: props with no stored price, props whose player
     team isn't in the game (the Arraez bug), avg juice on old picks

Usage (from repo root, needs SUPABASE_DB_URL in .env):
    python audit_mlb_props.py
    python audit_mlb_props.py --start 2026-08-01
    python audit_mlb_props.py --sport wnba        # same audit for WNBA
"""

import os, sys, argparse
from collections import defaultdict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from prop_edge import evaluate_prop, breakeven_pct

OLD_STRONG = 70
OLD_FADE = 30
MIN_GAMES = 5
EDGE_SWEEP = [0.0, 3.0, 5.0, 8.0, 12.0]


def profit_units(odds, won: bool) -> float:
    """1-unit stake, American odds. Missing odds -> assume -110."""
    o = -110 if odds in (None, 0) else float(odds)
    if not won:
        return -1.0
    return o / 100.0 if o > 0 else 100.0 / -o


def load_rows(sport: str, start: str):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT pp.date, pp.player_name, pp.stat, pp.line,
               pp.hit_rate_overall, pp.games_overall, pp.confidence_tier,
               pp.over_odds, pp.under_odds,
               pp.team_name, pp.game_home_team, pp.game_away_team,
               pr.hit, pr.actual_value
        FROM player_props pp
        JOIN prop_results pr
          ON pr.date = pp.date AND pr.player_name = pp.player_name
         AND pr.stat = pp.stat AND pr.line = pp.line AND pr.sport = pp.sport
        WHERE pp.sport = ?
          AND pp.date >= ?
          AND pr.hit IS NOT NULL
          AND pp.hit_rate_overall IS NOT NULL
        ORDER BY pp.date
    """, (sport, start))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def summarize(picks):
    """picks: list of (won: bool, odds, stat). Returns dict."""
    n = len(picks)
    if not n:
        return {"n": 0, "w": 0, "l": 0, "pct": 0.0, "units": 0.0, "roi": 0.0, "avg_be": 0.0}
    w = sum(1 for p in picks if p[0])
    units = sum(profit_units(p[1], p[0]) for p in picks)
    bes = [breakeven_pct(p[1]) for p in picks if breakeven_pct(p[1]) is not None]
    return {"n": n, "w": w, "l": n - w, "pct": round(w / n * 100, 1),
            "units": round(units, 2), "roi": round(units / n * 100, 1),
            "avg_be": round(sum(bes) / len(bes), 1) if bes else 0.0}


def fmt(label, s):
    return (f"  {label:<28} {s['n']:>4} picks  {s['w']:>3}-{s['l']:<3} "
            f"{s['pct']:>5}%  {s['units']:>+7.2f}u  ROI {s['roi']:>+6.1f}%  avg BE {s['avg_be']:>5}%")


def run(sport: str, start: str):
    rows = load_rows(sport, start)
    print(f"\n{'='*78}\n{sport.upper()} PROP AUDIT — graded props since {start}: {len(rows)}\n{'='*78}")
    if not rows:
        print("Nothing graded in this window."); return

    # ---- data quality ----
    no_price = [r for r in rows if r["over_odds"] in (None, 0) and r["under_odds"] in (None, 0)]
    mismatch = [r for r in rows if r["team_name"] and r["game_home_team"] and r["game_away_team"]
                and r["team_name"] not in (r["game_home_team"], r["game_away_team"])]
    print(f"\nData quality")
    print(f"  no stored price:            {len(no_price):>4}  ({len(no_price)/len(rows)*100:.1f}%)")
    print(f"  player team not in game:    {len(mismatch):>4}  ({len(mismatch)/len(rows)*100:.1f}%)")
    for r in mismatch[:5]:
        print(f"      {r['date']} {r['player_name']} ({r['team_name']}) filed under {r['game_away_team']} @ {r['game_home_team']}")

    # ---- old rule ----
    old = []
    for r in rows:
        if (r["games_overall"] or 0) < MIN_GAMES:
            continue
        hr = r["hit_rate_overall"]
        if r["confidence_tier"] == "green" and hr >= OLD_STRONG:
            old.append((r["hit"] == 1, r["over_odds"], r["stat"]))
        elif hr <= OLD_FADE:
            old.append((r["hit"] == 0, r["under_odds"], r["stat"]))
    print(f"\nOLD RULE  (hit_rate >= {OLD_STRONG} over / <= {OLD_FADE} under, min {MIN_GAMES}G, price-blind)")
    print(fmt("all", summarize(old)))
    by_stat = defaultdict(list)
    for p in old: by_stat[p[2]].append(p)
    for st, ps in sorted(by_stat.items(), key=lambda kv: -len(kv[1])):
        print(fmt(f"  {st}", summarize(ps)))

    # ---- new rule sweep ----
    print(f"\nNEW RULE  (Wilson-adjusted rate must beat book breakeven by MIN_EDGE_PTS; no price = no pick)")
    for min_edge in EDGE_SWEEP:
        new = []
        for r in rows:
            if (r["games_overall"] or 0) < MIN_GAMES:
                continue
            hr = r["hit_rate_overall"]
            side = "under" if hr <= 50 else "over"
            # still respect the old direction gates so we're comparing filters, not universes
            if side == "over" and not (r["confidence_tier"] == "green" and hr >= OLD_STRONG):
                continue
            if side == "under" and not (hr <= OLD_FADE):
                continue
            ev = evaluate_prop(hr, r["games_overall"], r["over_odds"], r["under_odds"], side, min_edge_pts=min_edge)
            if not ev["qualifies"]:
                continue
            won = (r["hit"] == 1) if side == "over" else (r["hit"] == 0)
            new.append((won, r["over_odds"] if side == "over" else r["under_odds"], r["stat"]))
        print(fmt(f"MIN_EDGE_PTS = {min_edge:<4}", summarize(new)))
        if min_edge == 3.0:
            by_stat = defaultdict(list)
            for p in new: by_stat[p[2]].append(p)
            for st, ps in sorted(by_stat.items(), key=lambda kv: -len(kv[1])):
                print(fmt(f"    {st}", summarize(ps)))

    print("\nHow to read it: a rule is only worth shipping if ROI is positive on a sample big enough\n"
          "to mean something (50+ picks). If every MIN_EDGE_PTS row is negative, the props model\n"
          "itself isn't beating the book on this sport and no filter fixes that.\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="mlb")
    ap.add_argument("--start", default="2026-07-01")
    a = ap.parse_args()
    run(a.sport, a.start)
