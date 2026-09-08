"""
audit_wnba_selector.py — Culture & Pulse Analytics
===================================================
Head-to-head backtest of the LIVE wnba_props_alert.py rule vs the
proposed projection-based selector, on the same graded props.

    python audit_wnba_selector.py
    python audit_wnba_selector.py --start 2026-08-01
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

PROPOSED_STATS = ("pa", "pra", "pts")

def profit_units(odds, won):
    o = -110 if odds in (None, 0) else float(odds)
    return (o / 100.0 if o > 0 else 100.0 / -o) if won else -1.0

def summarize(picks):
    n = len(picks)
    if not n: return {"n":0,"w":0,"l":0,"pct":0.0,"units":0.0,"roi":0.0}
    w = sum(1 for p in picks if p[0]); u = sum(profit_units(p[1], p[0]) for p in picks)
    return {"n":n,"w":w,"l":n-w,"pct":round(w/n*100,1),"units":round(u,2),"roi":round(u/n*100,1)}

def fmt(label, s):
    return f"  {label:<44} {s['n']:>4} picks  {s['w']:>3}-{s['l']:<3} {s['pct']:>5}%  {s['units']:>+7.2f}u  ROI {s['roi']:>+6.1f}%"

def run(start):
    conn = get_conn(); c = conn.cursor()
    c.execute("""
        SELECT pp.date, pp.player_name, pp.stat, pp.line, pp.games_overall, pp.hit_rate_overall,
               pp.confidence_tier, pp.over_odds, pp.under_odds, pp.injury_status,
               pp.projected_stat, pp.projection_edge_pct, pp.projection_direction, pp.projection_tier,
               pr.hit
        FROM player_props pp
        JOIN prop_results pr ON pr.date = pp.date AND pr.player_name = pp.player_name
         AND pr.stat = pp.stat AND pr.line = pp.line AND pr.sport = pp.sport
        WHERE pp.sport = 'wnba' AND pp.date >= ? AND pr.hit IS NOT NULL
    """, (start,))
    rows = [dict(r) for r in c.fetchall()]; conn.close()
    print(f"\nWNBA SELECTOR HEAD-TO-HEAD — graded props since {start}: {len(rows)}\n")

    # LIVE rule: green tier & hit_rate>=80 -> over; hit_rate<=20 -> under; min 5G
    live = []
    for r in rows:
        if (r["games_overall"] or 0) < 5 or r["hit_rate_overall"] is None: continue
        hr = r["hit_rate_overall"]
        if r["confidence_tier"] == "green" and hr >= 80: live.append((r["hit"]==1, r["over_odds"], r["stat"]))
        elif hr <= 20: live.append((r["hit"]==0, r["under_odds"], r["stat"]))
    print("LIVE RULE  (hit_rate >= 80 over / <= 20 under, price-blind) — what Discord gets today")
    print(fmt("all", summarize(live)))

    def is_over(r): return (r["projection_direction"] or "").lower().startswith("o")

    print("\nPROPOSED  (projection_tier = green, OVERS only)")
    for stats_label, stats in (("all stats", None), (f"stats in {PROPOSED_STATS}", PROPOSED_STATS)):
        for min_edge in (0, 10, 20, 35):
            ps = []
            for r in rows:
                if r["projection_tier"] != "green" or not is_over(r): continue
                if stats and r["stat"] not in stats: continue
                e = r["projection_edge_pct"]
                if e is None or float(e) < min_edge: continue
                ps.append((r["hit"]==1, r["over_odds"], r["stat"]))
            print(fmt(f"{stats_label}, edge_pct >= {min_edge}", summarize(ps)))
        print()

    print("PROPOSED, stats filter, edge >= 0 — by month (does it hold up over time?)")
    bym = defaultdict(list)
    for r in rows:
        if r["projection_tier"] != "green" or not is_over(r) or r["stat"] not in PROPOSED_STATS: continue
        bym[r["date"][:7]].append((r["hit"]==1, r["over_odds"], r["stat"]))
    for m in sorted(bym): print(fmt(f"  {m}", summarize(bym[m])))

    print("\nPROPOSED, stats filter — with vs without an injury flag on the player")
    flagged, clean = [], []
    for r in rows:
        if r["projection_tier"] != "green" or not is_over(r) or r["stat"] not in PROPOSED_STATS: continue
        (flagged if r.get("injury_status") else clean).append((r["hit"]==1, r["over_odds"], r["stat"]))
    print(fmt("  no injury status", summarize(clean)))
    print(fmt("  has injury status", summarize(flagged)))
    print()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--start", default="2026-07-01")
    run(ap.parse_args().start)
