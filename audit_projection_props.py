"""
audit_projection_props.py — Culture & Pulse Analytics
======================================================
Backtest picking props by the PROJECTION ENGINE (projected_stat vs line,
projection_direction, projection_tier) instead of by historical hit rate.
Same graded data as audit_mlb_props.py, different selector.

If this is positive ROI, the fix is swapping the selector in the alert.
If it's negative too, the props model needs a rebuild.

Usage (repo root, SUPABASE_DB_URL in .env):
    python audit_projection_props.py
    python audit_projection_props.py --sport wnba
    python audit_projection_props.py --start 2026-08-01
"""
import os, sys, argparse
from collections import defaultdict

try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError:
    pass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from prop_edge import breakeven_pct

MIN_GAMES = 5


def profit_units(odds, won):
    o = -110 if odds in (None, 0) else float(odds)
    if not won: return -1.0
    return o / 100.0 if o > 0 else 100.0 / -o


def summarize(picks):
    n = len(picks)
    if not n: return {"n":0,"w":0,"l":0,"pct":0.0,"units":0.0,"roi":0.0,"avg_be":0.0}
    w = sum(1 for p in picks if p[0])
    units = sum(profit_units(p[1], p[0]) for p in picks)
    bes = [breakeven_pct(p[1]) for p in picks if breakeven_pct(p[1]) is not None]
    return {"n":n,"w":w,"l":n-w,"pct":round(w/n*100,1),"units":round(units,2),
            "roi":round(units/n*100,1),"avg_be":round(sum(bes)/len(bes),1) if bes else 0.0}


def fmt(label, s):
    return (f"  {label:<30} {s['n']:>4} picks  {s['w']:>3}-{s['l']:<3} {s['pct']:>5}%  "
            f"{s['units']:>+7.2f}u  ROI {s['roi']:>+6.1f}%  avg BE {s['avg_be']:>5}%")


def run(sport, start):
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        SELECT pp.date, pp.player_name, pp.stat, pp.line, pp.games_overall,
               pp.hit_rate_overall, pp.over_odds, pp.under_odds,
               pp.projected_stat, pp.projection_edge, pp.projection_edge_pct,
               pp.projection_direction, pp.projection_tier,
               pr.hit, pr.actual_value
        FROM player_props pp
        JOIN prop_results pr
          ON pr.date = pp.date AND pr.player_name = pp.player_name
         AND pr.stat = pp.stat AND pr.line = pp.line AND pr.sport = pp.sport
        WHERE pp.sport = ? AND pp.date >= ? AND pr.hit IS NOT NULL
        ORDER BY pp.date
    """, (sport, start))
    rows = [dict(r) for r in c.fetchall()]; conn.close()

    print(f"\n{'='*80}\n{sport.upper()} PROJECTION-BASED PROP AUDIT — graded props since {start}: {len(rows)}\n{'='*80}")
    have_proj = [r for r in rows if r["projected_stat"] is not None and r["projection_direction"]]
    print(f"  rows with a saved projection: {len(have_proj)} ({len(have_proj)/max(len(rows),1)*100:.1f}%)")
    if not have_proj:
        print("  No projections saved on graded rows — the engine wasn't writing to player_props in this window."); return

    def dirn(r):
        d = (r["projection_direction"] or "").lower()
        return "over" if d.startswith("o") or d == "over" else "under" if d.startswith("u") else None

    def pick(r):
        side = dirn(r)
        if not side: return None
        won = (r["hit"] == 1) if side == "over" else (r["hit"] == 0)
        odds = r["over_odds"] if side == "over" else r["under_odds"]
        return (won, odds, r["stat"], side)

    # 1) by projection tier
    print("\nBY PROJECTION TIER (follow the engine's direction)")
    by_tier = defaultdict(list)
    for r in have_proj:
        p = pick(r)
        if p: by_tier[r["projection_tier"] or "none"].append(p)
    for t in ["green", "yellow", "red", "none"]:
        if by_tier.get(t): print(fmt(f"tier = {t}", summarize(by_tier[t])))

    # 2) green only, by stat and by side
    green = by_tier.get("green", [])
    print("\nGREEN ONLY — by stat")
    bs = defaultdict(list)
    for p in green: bs[p[2]].append(p)
    for st, ps in sorted(bs.items(), key=lambda kv: -len(kv[1])): print(fmt(f"  {st}", summarize(ps)))
    print("\nGREEN ONLY — by side")
    for side in ("over", "under"):
        print(fmt(f"  {side}", summarize([p for p in green if p[3] == side])))

    # 3) edge-pct sweep on the raw projection edge (abs), any tier
    print("\nSWEEP |projection_edge_pct| >= X (any tier)")
    for x in (0, 10, 20, 35, 50, 75):
        ps = []
        for r in have_proj:
            e = r["projection_edge_pct"]
            if e is None or abs(float(e)) < x: continue
            p = pick(r)
            if p: ps.append(p)
        print(fmt(f"edge_pct >= {x}", summarize(ps)))

    # 4) agreement: projection AND hit-rate history point the same way
    print("\nAGREEMENT — projection direction matches hit-rate history (>=70 over / <=30 under), min 5G")
    agree = []
    for r in have_proj:
        if (r["games_overall"] or 0) < MIN_GAMES: continue
        hr = r["hit_rate_overall"]; side = dirn(r)
        if hr is None or not side: continue
        if (side == "over" and hr >= 70) or (side == "under" and hr <= 30):
            p = pick(r)
            if p: agree.append(p)
    print(fmt("both agree", summarize(agree)))
    print(fmt("  green tier + agree", summarize([p for p in agree if p in green])))
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", default="mlb"); ap.add_argument("--start", default="2026-07-01")
    a = ap.parse_args(); run(a.sport, a.start)
