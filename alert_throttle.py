"""
alert_throttle.py — Culture & Pulse Analytics
=============================================
Controls how many and which alerts fire per slate.

Rules:
  1. Max 3 picks per sport per day (configurable per sport)
  2. One pick per game maximum — no correlated same-game picks
  3. Picks ranked by edge — strongest edge fires first
  4. Minimum edge threshold per sport before alert qualifies
  5. If all picks are from one team's slate (e.g. 4 WNBA home
     favorites), cap to avoid overexposure on one narrative

Usage:
  from alert_throttle import throttle_bets
  clean_bets = throttle_bets(bets, sport)
"""

from datetime import datetime
from typing import Optional


# ─────────────────────────────────────────────────────────────
# CONFIG — adjust per sport as v3 data accumulates
# ─────────────────────────────────────────────────────────────

THROTTLE_CONFIG = {
    "wnba": {
        "max_picks":     3,     # max alerts per slate
        "min_edge":      8.0,   # minimum edge % to qualify
        "min_prob":     65.0,   # minimum confidence % to qualify
    },
    "nba": {
        "max_picks":     3,
        "min_edge":      8.0,
        "min_prob":     65.0,
    },
    "nfl": {
        "max_picks":     2,     # fewer games per week, be selective
        "min_edge":     12.0,   # raised 2026-09-02: uncalibrated until 40 graded picks
        "min_prob":     65.0,
    },
    "ncaaf": {
        "max_picks":     3,
        "min_edge":     10.0,   # raised 2026-09-02: uncalibrated until 40 graded picks
        "min_prob":     65.0,
    },
    "ncaab": {
        "max_picks":     4,     # high volume sport, allow slightly more
        "min_edge":      8.0,
        "min_prob":     65.0,
    },
}

DEFAULT_CONFIG = {
    "max_picks":  3,
    "min_edge":   8.0,
    "min_prob":  65.0,
}


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def get_edge_pct(bet: dict) -> float:
    """Normalize edge to percentage regardless of how it's stored."""
    edge = bet.get("edge", 0)
    # edge stored as decimal (0.185) or percentage (18.5)
    if isinstance(edge, float) and edge < 1.0:
        return round(edge * 100, 2)
    return round(float(edge), 2)


def get_confidence(bet: dict) -> float:
    """Get model confidence for the picked team."""
    model_prob  = bet.get("model_prob", 50)
    game        = bet.get("game", "")
    bet_label   = bet.get("bet", "")
    parts       = game.split(" @ ")
    home_team   = parts[1] if len(parts) == 2 else ""
    bet_on_home = home_team.lower() in bet_label.lower()
    return model_prob if bet_on_home else round(100 - model_prob, 1)


def get_game_key(bet: dict) -> str:
    """Unique key per game — prevents same-game correlated picks."""
    game  = bet.get("game", "")
    parts = game.split(" @ ")
    if len(parts) == 2:
        # Sort teams alphabetically so home/away order doesn't matter
        return "_vs_".join(sorted([parts[0].strip(), parts[1].strip()]))
    return game


def get_home_away_balance(bets: list) -> tuple:
    """Returns (home_count, away_count) for a list of bets."""
    home = 0
    away = 0
    for bet in bets:
        game      = bet.get("game", "")
        bet_label = bet.get("bet", "")
        parts     = game.split(" @ ")
        home_team = parts[1] if len(parts) == 2 else ""
        if home_team.lower() in bet_label.lower():
            home += 1
        else:
            away += 1
    return home, away


# ─────────────────────────────────────────────────────────────
# MAIN THROTTLE FUNCTION
# ─────────────────────────────────────────────────────────────

def throttle_bets(bets: list, sport: str) -> tuple:
    """
    Filters and ranks bets for a sport slate.

    Returns (clean_bets, suppressed_bets, throttle_log)
      clean_bets:    picks that made the cut
      suppressed:    picks filtered out with reasons
      throttle_log:  summary string for logging
    """
    config     = THROTTLE_CONFIG.get(sport.lower(), DEFAULT_CONFIG)
    max_picks  = config["max_picks"]
    min_edge   = config["min_edge"]
    min_prob   = config["min_prob"]

    suppressed  = []
    qualified   = []
    seen_games  = set()

    # ── Step 1: Filter by minimum thresholds ──
    for bet in bets:
        edge = get_edge_pct(bet)
        prob = get_confidence(bet)
        game = bet.get("game", "unknown")

        if edge < min_edge:
            suppressed.append({
                "game":   game,
                "bet":    bet.get("bet", ""),
                "reason": f"Edge {edge:.1f}% below minimum {min_edge:.0f}%",
            })
            continue

        if prob < min_prob:
            suppressed.append({
                "game":   game,
                "bet":    bet.get("bet", ""),
                "reason": f"Confidence {prob:.1f}% below minimum {min_prob:.0f}%",
            })
            continue

        qualified.append(bet)

    # ── Step 2: Deduplicate — one pick per game ──
    deduped = []
    for bet in qualified:
        game_key = get_game_key(bet)
        if game_key in seen_games:
            suppressed.append({
                "game":   bet.get("game", ""),
                "bet":    bet.get("bet", ""),
                "reason": "Correlated pick — same game already selected",
            })
            continue
        seen_games.add(game_key)
        deduped.append(bet)

    # ── Step 3: Rank by edge descending ──
    ranked = sorted(deduped, key=lambda b: get_edge_pct(b), reverse=True)

    # ── Step 4: Apply max picks cap ──
    clean_bets = ranked[:max_picks]
    capped     = ranked[max_picks:]

    for bet in capped:
        suppressed.append({
            "game":   bet.get("game", ""),
            "bet":    bet.get("bet", ""),
            "reason": f"Slate cap reached ({max_picks} max picks for {sport.upper()})",
        })

    # ── Step 5: Build log summary ──
    home_ct, away_ct = get_home_away_balance(clean_bets)
    log_lines = [
        f"  Throttle: {len(bets)} raw → {len(qualified)} qualified → {len(clean_bets)} fired",
        f"  Edge filter: {min_edge:.0f}%+ | Confidence: {min_prob:.0f}%+ | Cap: {max_picks}",
        f"  Balance: {home_ct} home / {away_ct} away picks",
    ]
    if suppressed:
        log_lines.append(f"  Suppressed {len(suppressed)} picks:")
        for s in suppressed:
            log_lines.append(f"    ✗ {s['game']} — {s['reason']}")

    throttle_log = "\n".join(log_lines)

    return clean_bets, suppressed, throttle_log


# ─────────────────────────────────────────────────────────────
# SLATE SUMMARY LINE
# ─────────────────────────────────────────────────────────────

def format_throttle_summary(clean_bets: list, suppressed: list, sport: str) -> str:
    """
    Returns a one-line summary to append to the slate message.
    Shows how many picks were filtered and why.
    """
    total   = len(clean_bets) + len(suppressed)
    fired   = len(clean_bets)
    dropped = len(suppressed)

    if dropped == 0:
        return f"<i>All {fired} qualifying edge(s) sent.</i>"

    reasons = {}
    for s in suppressed:
        r = s["reason"].split("—")[-1].strip() if "—" in s["reason"] else s["reason"]
        # Simplify reason for display
        if "Edge" in r:
            key = "below edge threshold"
        elif "Confidence" in r:
            key = "below confidence threshold"
        elif "Correlated" in r:
            key = "same-game duplicate"
        elif "cap" in r.lower():
            key = "slate cap"
        else:
            key = "filtered"
        reasons[key] = reasons.get(key, 0) + 1

    reason_str = ", ".join(f"{v} {k}" for k, v in reasons.items())
    return f"<i>{fired} of {total} edges sent — {dropped} filtered ({reason_str})</i>"


if __name__ == "__main__":
    # Quick test
    test_bets = [
        {"game": "Minnesota Lynx @ Atlanta Dream", "bet": "Atlanta Dream ML",
         "model_prob": 72, "edge": 15.2},
        {"game": "Las Vegas Aces @ New York Liberty", "bet": "New York Liberty ML",
         "model_prob": 68, "edge": 12.1},
        {"game": "Las Vegas Aces @ New York Liberty", "bet": "Las Vegas Aces ML",
         "model_prob": 32, "edge": 6.0},   # same game — should be deduped
        {"game": "Seattle Storm @ Indiana Fever", "bet": "Indiana Fever ML",
         "model_prob": 71, "edge": 9.4},
        {"game": "Chicago Sky @ Phoenix Mercury", "bet": "Phoenix Mercury ML",
         "model_prob": 66, "edge": 7.2},   # should be capped (4th pick, max=3)
        {"game": "Dallas Wings @ Washington Mystics", "bet": "Dallas Wings ML",
         "model_prob": 55, "edge": 4.1},   # below edge threshold
    ]

    clean, suppressed, log = throttle_bets(test_bets, "wnba")
    print(f"\nClean bets ({len(clean)}):")
    for b in clean:
        print(f"  ✅ {b['game']} | {b['bet']} | Edge: {get_edge_pct(b)}%")
    print(f"\n{log}")
    print(f"\nSummary line: {format_throttle_summary(clean, suppressed, 'wnba')}")
