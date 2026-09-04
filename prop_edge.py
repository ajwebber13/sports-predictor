"""
prop_edge.py — Culture & Pulse Analytics
=========================================
Shared prop math so mlb_props_alert.py and pick_of_the_day.py stop
treating a raw hit rate as an edge.

Two problems this fixes:
  1. Price-blind picks. A 76% hit rate on oHITS 0.5 looks strong, but
     the book prices that line around -300 (breakeven 75%). Zero edge.
     Every pick now compares hit rate to the breakeven implied by the
     stored over_odds/under_odds.
  2. Small-sample 100%s. 15-for-15 is not a 100% player. The Wilson
     lower bound (z=1.28) on 15/15 is ~88%. Ranking and display use the
     lower bound so a 15-game streak can't beat a 40-game 85%.
"""

import math


def breakeven_pct(american_odds) -> float | None:
    """Win rate needed to break even on this price. -300 -> 75.0, +150 -> 40.0."""
    if american_odds is None:
        return None
    try:
        o = float(american_odds)
    except (TypeError, ValueError):
        return None
    if o == 0:
        return None
    if o < 0:
        return round(-o / (-o + 100) * 100, 1)
    return round(100 / (o + 100) * 100, 1)


def wilson_lower_pct(rate_pct: float, n: int, z: float = 1.28) -> float:
    """One-sided ~90% Wilson lower bound (z=1.28) of a hit rate (as a percent) on n games."""
    if not n or n <= 0 or rate_pct is None:
        return 0.0
    p = max(0.0, min(1.0, rate_pct / 100.0))
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((centre - spread) / denom * 100, 1)


def evaluate_prop(hit_rate_overall, games_overall, over_odds, under_odds,
                  side: str, min_edge_pts: float = 3.0) -> dict:
    """
    side: "over" or "under".
    Returns a dict with raw_pct, adj_pct (Wilson LB), breakeven_pct,
    edge_pts and qualifies (bool). If odds are missing, breakeven is
    None and qualifies is False — a prop with no price is not a play.
    """
    if hit_rate_overall is None or not games_overall:
        return {"raw_pct": None, "adj_pct": None, "breakeven_pct": None,
                "edge_pts": None, "qualifies": False}
    raw = float(hit_rate_overall) if side == "over" else 100.0 - float(hit_rate_overall)
    adj = wilson_lower_pct(raw, int(games_overall))
    odds = over_odds if side == "over" else under_odds
    be = breakeven_pct(odds)
    if be is None:
        return {"raw_pct": round(raw, 1), "adj_pct": adj, "breakeven_pct": None,
                "edge_pts": None, "qualifies": False}
    edge = round(adj - be, 1)
    return {"raw_pct": round(raw, 1), "adj_pct": adj, "breakeven_pct": be,
            "edge_pts": edge, "qualifies": edge >= min_edge_pts}


if __name__ == "__main__":
    # Quick sanity checks
    assert breakeven_pct(-110) == 52.4
    assert breakeven_pct(-300) == 75.0
    assert breakeven_pct(150) == 40.0
    print("Tommy White 15/15 under @ -250:", evaluate_prop(0.0, 15, None, -250, "under"))
    print("Otto Lopez 76.4% over @ -300:", evaluate_prop(76.4, 40, -300, None, "over"))
    print("Real edge 85% on 40g @ -200:", evaluate_prop(85.0, 40, -200, None, "over"))
    print("No odds:", evaluate_prop(90.0, 30, None, None, "over"))
