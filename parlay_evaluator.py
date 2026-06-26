"""
parlay_evaluator.py — Culture & Pulse Analytics
================================================
Evaluates multi-leg parlays by:
  1. Pulling model prob / hit rate for each leg
  2. Detecting correlated legs and adjusting combined probability
  3. Flagging weak legs (< 55% probability)
  4. Assigning a confidence tier: Green / Yellow / Red

Leg types supported:
  - team_ml:   team moneyline  (e.g. "Las Vegas Aces ML")
  - player_prop: player over   (e.g. "A'ja Wilson o22.5 pts")
  - spread:    point spread    (e.g. "Minnesota Lynx -5.5")

Usage (CLI):
    python parlay_evaluator.py

Usage (import):
    from parlay_evaluator import evaluate_parlay

    legs = [
        {"type": "team_ml",      "team": "Las Vegas Aces",  "prob": 0.65},
        {"type": "player_prop",  "player": "A'ja Wilson",   "stat": "pts", "line": 22.5, "prob": 0.70},
    ]
    result = evaluate_parlay(legs)
"""

import os
import sys
import json
import sqlite3
from itertools import combinations

DB_PATH = os.path.join(os.path.dirname(__file__), "cp_analytics.db")

# ─────────────────────────────────────────────
# CORRELATION RULES
# ─────────────────────────────────────────────

# Correlation penalty applied to combined probability
# These are multiplicative adjustments (e.g. 0.88 = reduce by 12%)
CORRELATION_RULES = [
    {
        "name": "Team ML + same-team star prop (positive corr)",
        "description": "Star player scores more when team wins — legs are NOT independent",
        "match": lambda a, b: (
            a["type"] == "team_ml" and b["type"] == "player_prop"
            and a.get("team") == b.get("team")
        ),
        "adjustment": 0.88,  # reduce combined prob by 12%
        "direction": "positive",  # both legs tend to hit together
    },
    {
        "name": "Two props from same team",
        "description": "Two players on same team share usage — one going big can limit the other",
        "match": lambda a, b: (
            a["type"] == "player_prop" and b["type"] == "player_prop"
            and a.get("team") == b.get("team")
            and a.get("stat") in ["pts", "ast"] and b.get("stat") in ["pts", "ast"]
        ),
        "adjustment": 0.90,
        "direction": "negative",  # legs compete with each other
    },
    {
        "name": "Team ML win + opposing star prop over",
        "description": "Star player scores less when their team loses — bad parlay",
        "match": lambda a, b: (
            a["type"] == "team_ml" and b["type"] == "player_prop"
            and a.get("team") != b.get("team")
            and a.get("opponent") == b.get("team")
        ),
        "adjustment": 0.82,  # reduce by 18% — significant negative correlation
        "direction": "negative",
    },
    {
        "name": "Same game total over + player points over",
        "description": "High-scoring game benefits player points — modest positive correlation",
        "match": lambda a, b: (
            a["type"] == "total" and b["type"] == "player_prop"
            and b.get("stat") == "pts"
            and (a.get("home_team") == b.get("team") or a.get("away_team") == b.get("team"))
        ),
        "adjustment": 0.93,
        "direction": "positive",
    },
    {
        "name": "Two team MLs from same game",
        "description": "Only one team can win — mutually exclusive legs",
        "match": lambda a, b: (
            a["type"] == "team_ml" and b["type"] == "team_ml"
            and (
                (a.get("team") == b.get("opponent")) or
                (a.get("opponent") == b.get("team"))
            )
        ),
        "adjustment": 0.0,  # impossible — zero out
        "direction": "impossible",
    },
]


# ─────────────────────────────────────────────
# PROBABILITY HELPERS
# ─────────────────────────────────────────────

def american_to_prob(ml: int) -> float:
    if ml > 0:
        return 100 / (ml + 100)
    return abs(ml) / (abs(ml) + 100)


def combined_prob_independent(probs: list) -> float:
    result = 1.0
    for p in probs:
        result *= p
    return result


def american_parlay_payout(legs: list) -> float:
    """Calculate true parlay payout multiplier for N independent legs."""
    payout = 1.0
    for leg in legs:
        ml = leg.get("odds")
        if ml:
            if ml > 0:
                payout *= (1 + ml / 100)
            else:
                payout *= (1 + 100 / abs(ml))
    return round(payout, 2)


# ─────────────────────────────────────────────
# CORRELATION DETECTION
# ─────────────────────────────────────────────

def detect_correlations(legs: list) -> list:
    """
    Check all leg pairs against correlation rules.
    Returns list of triggered correlation dicts.
    """
    triggered = []
    for i, j in combinations(range(len(legs)), 2):
        a, b = legs[i], legs[j]
        for rule in CORRELATION_RULES:
            if rule["match"](a, b) or rule["match"](b, a):
                triggered.append({
                    "rule":       rule["name"],
                    "description": rule["description"],
                    "leg_a":      _leg_label(a),
                    "leg_b":      _leg_label(b),
                    "adjustment": rule["adjustment"],
                    "direction":  rule["direction"],
                })
                break
    return triggered


def _leg_label(leg: dict) -> str:
    if leg["type"] == "team_ml":
        return f"{leg.get('team', '?')} ML"
    if leg["type"] == "player_prop":
        return f"{leg.get('player', '?')} o{leg.get('line', '?')} {leg.get('stat', '?')}"
    if leg["type"] == "spread":
        return f"{leg.get('team', '?')} {leg.get('spread', '?')}"
    if leg["type"] == "total":
        return f"{leg.get('home_team', '?')} vs {leg.get('away_team', '?')} o/u {leg.get('line', '?')}"
    return str(leg)


# ─────────────────────────────────────────────
# MAIN EVALUATOR
# ─────────────────────────────────────────────

def evaluate_parlay(legs: list) -> dict:
    """
    Evaluate a parlay.

    Each leg dict must include:
        type:   "team_ml" | "player_prop" | "spread" | "total"
        prob:   float 0-1  (model probability or hit rate)

    Optional per type:
        team_ml:      team, opponent, odds (American ML)
        player_prop:  player, team, stat, line, odds
        spread:       team, spread, odds
        total:        home_team, away_team, line, direction (over/under), odds

    Returns:
        {
          legs:               list of leg dicts with labels
          raw_combined_prob:  float (independent assumption)
          adj_combined_prob:  float (after correlation adjustments)
          correlations:       list of triggered rules
          weak_legs:          list of legs with prob < 0.55
          impossible:         bool
          confidence_tier:    "green" | "yellow" | "red"
          payout_multiplier:  float | None
          summary:            str
        }
    """
    if not legs:
        return {"error": "No legs provided"}

    # Validate
    for i, leg in enumerate(legs):
        if "prob" not in leg:
            return {"error": f"Leg {i+1} missing 'prob' field"}
        if not (0 < leg["prob"] <= 1):
            return {"error": f"Leg {i+1} prob must be between 0 and 1 (got {leg['prob']})"}

    # Raw combined probability
    probs           = [leg["prob"] for leg in legs]
    raw_combined    = combined_prob_independent(probs)

    # Detect correlations
    correlations    = detect_correlations(legs)
    impossible      = any(c["direction"] == "impossible" for c in correlations)

    if impossible:
        return {
            "legs":             [_leg_label(l) for l in legs],
            "raw_combined_prob": 0.0,
            "adj_combined_prob": 0.0,
            "correlations":     correlations,
            "weak_legs":        [],
            "impossible":       True,
            "confidence_tier":  "red",
            "payout_multiplier": None,
            "summary": "❌ IMPOSSIBLE PARLAY — two legs from the same game (only one team can win).",
        }

    # Apply correlation adjustments
    adj_combined = raw_combined
    for corr in correlations:
        adj_combined *= corr["adjustment"]
    adj_combined = round(adj_combined, 4)

    # Flag weak legs
    weak_legs = [
        {"leg": _leg_label(l), "prob": round(l["prob"] * 100, 1)}
        for l in legs if l["prob"] < 0.55
    ]

    # Payout
    payout = american_parlay_payout(legs) if any(l.get("odds") for l in legs) else None

    # Confidence tier
    tier = _confidence_tier(adj_combined, weak_legs, correlations)

    # Summary
    summary = _build_summary(legs, raw_combined, adj_combined, correlations, weak_legs, tier, payout)

    return {
        "legs":              [_leg_label(l) for l in legs],
        "leg_probs":         {_leg_label(l): round(l["prob"] * 100, 1) for l in legs},
        "raw_combined_prob": round(raw_combined * 100, 1),
        "adj_combined_prob": round(adj_combined * 100, 1),
        "correlations":      correlations,
        "weak_legs":         weak_legs,
        "impossible":        False,
        "confidence_tier":   tier,
        "payout_multiplier": payout,
        "summary":           summary,
    }


def _confidence_tier(adj_prob: float, weak_legs: list, correlations: list) -> str:
    """
    🟢 Green:  adj_prob >= 0.40, no weak legs, no negative correlations
    🟡 Yellow: adj_prob >= 0.25, <=1 weak leg, or has correlation adjustment
    🔴 Red:    adj_prob < 0.25, 2+ weak legs, or negative correlation
    """
    has_negative_corr = any(c["direction"] == "negative" for c in correlations)

    if adj_prob >= 0.40 and not weak_legs and not has_negative_corr:
        return "green"
    elif adj_prob >= 0.25 and len(weak_legs) <= 1:
        return "yellow"
    else:
        return "red"


def _build_summary(legs, raw, adj, correlations, weak_legs, tier, payout) -> str:
    tier_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(tier, "")
    lines = [f"{tier_emoji} {tier.upper()} PARLAY — {len(legs)} legs"]
    lines.append("")

    for leg in legs:
        prob_pct = round(leg["prob"] * 100, 1)
        flag     = " ⚠️ weak" if leg["prob"] < 0.55 else ""
        lines.append(f"  • {_leg_label(leg)} — {prob_pct}%{flag}")

    lines.append("")
    lines.append(f"  Raw combined prob:  {round(raw * 100, 1)}%")

    if correlations:
        lines.append(f"  Correlation adj:    {round(adj * 100, 1)}% (after {len(correlations)} adjustment(s))")
        for c in correlations:
            symbol = "⬇️" if c["direction"] == "negative" else "↔️"
            lines.append(f"    {symbol} {c['rule']}")
    else:
        lines.append(f"  No correlations detected.")

    if payout:
        lines.append(f"  Payout multiplier:  {payout}x")

    if weak_legs:
        lines.append("")
        lines.append("  Weak legs (< 55%):")
        for w in weak_legs:
            lines.append(f"    ❌ {w['leg']} ({w['prob']}%)")

    lines.append("")
    if tier == "green":
        lines.append("  ✅ Solid parlay — all legs strong, no harmful correlations.")
    elif tier == "yellow":
        lines.append("  ⚠️  Proceed with caution — correlation or weak leg present.")
    else:
        lines.append("  ❌ Avoid — low combined probability or negative correlation.")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# FETCH LEG PROB FROM DB
# ─────────────────────────────────────────────

def get_model_prob(team: str, date: str = None) -> float | None:
    """Pull today's model probability for a team ML from predictions table."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c    = conn.cursor()

    if not date:
        from datetime import datetime, timezone, timedelta
        date = (datetime.now(timezone.utc) + timedelta(hours=-5)).strftime("%Y-%m-%d")

    c.execute("""
        SELECT model_prob, predicted_winner, home_team, away_team
        FROM predictions
        WHERE date = ?
          AND (home_team LIKE ? OR away_team LIKE ?)
        ORDER BY created_at DESC
        LIMIT 1
    """, (date, f"%{team}%", f"%{team}%"))
    row = c.fetchone()
    conn.close()

    if not row:
        return None

    winner = row["predicted_winner"]
    model_prob = row["model_prob"]

    # If team is the predicted winner, return model_prob; otherwise return complement
    if team.lower() in (winner or "").lower():
        return round(model_prob / 100, 4)
    else:
        return round((100 - model_prob) / 100, 4)


def get_prop_prob(player: str, stat: str, line: float) -> float | None:
    """Pull hit rate from player_props table if available, else game log."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c    = conn.cursor()

    # Check player_props first
    from datetime import datetime, timezone, timedelta
    today = (datetime.now(timezone.utc) + timedelta(hours=-5)).strftime("%Y-%m-%d")

    c.execute("""
        SELECT hit_rate_overall FROM player_props
        WHERE date = ? AND player_name LIKE ? AND stat = ? AND line = ?
        LIMIT 1
    """, (today, f"%{player}%", stat, line))
    row = c.fetchone()
    if row and row["hit_rate_overall"]:
        conn.close()
        return round(row["hit_rate_overall"] / 100, 4)

    # Fall back to game log hit rate
    c.execute(f"""
        SELECT COUNT(*) as games,
               SUM(CASE WHEN {stat} > ? THEN 1 ELSE 0 END) as hits
        FROM wnba_game_log
        WHERE player_name LIKE ? AND minutes > 0
    """, (line, f"%{player}%"))
    row = c.fetchone()
    conn.close()

    if row and row["games"] >= 5:
        return round(row["hits"] / row["games"], 4)
    return None


# ─────────────────────────────────────────────
# INTERACTIVE CLI
# ─────────────────────────────────────────────

def interactive_builder():
    """Walk the user through building a parlay interactively."""
    print("\n" + "="*55)
    print("  C&P Parlay Evaluator")
    print("="*55)
    print("  Add legs one at a time. Type 'done' to evaluate.")
    print("  Types: team_ml | player_prop | spread")
    print("="*55 + "\n")

    legs = []

    while True:
        leg_num = len(legs) + 1
        print(f"  Leg {leg_num} (or 'done' to evaluate, 'quit' to exit):")
        leg_type = input("    Type (team_ml / player_prop / spread): ").strip().lower()

        if leg_type in ("done", "d"):
            break
        if leg_type in ("quit", "q", "exit"):
            sys.exit(0)
        if leg_type not in ("team_ml", "player_prop", "spread"):
            print("    Invalid type. Use: team_ml, player_prop, spread\n")
            continue

        leg = {"type": leg_type}

        if leg_type == "team_ml":
            leg["team"]     = input("    Team name: ").strip()
            leg["opponent"] = input("    Opponent (for correlation check): ").strip()
            leg["odds"]     = _prompt_int("    Odds (American, e.g. -145 or +120): ")

            # Try to auto-fetch model prob
            auto_prob = get_model_prob(leg["team"])
            if auto_prob:
                print(f"    Auto-fetched model prob: {round(auto_prob*100,1)}%")
                use = input("    Use this? (y/n): ").strip().lower()
                if use == "y":
                    leg["prob"] = auto_prob
                else:
                    pct = _prompt_float("    Enter probability % (e.g. 65): ")
                    leg["prob"] = pct / 100
            else:
                pct = _prompt_float("    Enter probability % (e.g. 65): ")
                leg["prob"] = pct / 100

        elif leg_type == "player_prop":
            leg["player"] = input("    Player name: ").strip()
            leg["team"]   = input("    Player's team: ").strip()
            leg["stat"]   = input("    Stat (pts/reb/ast/stl/blk): ").strip().lower()
            leg["line"]   = _prompt_float("    Line (e.g. 18.5): ")
            leg["odds"]   = _prompt_int("    Over odds (American, e.g. -115): ")

            # Try to auto-fetch hit rate
            auto_prob = get_prop_prob(leg["player"], leg["stat"], leg["line"])
            if auto_prob:
                print(f"    Auto-fetched hit rate: {round(auto_prob*100,1)}%")
                use = input("    Use this? (y/n): ").strip().lower()
                if use == "y":
                    leg["prob"] = auto_prob
                else:
                    pct = _prompt_float("    Enter probability % (e.g. 65): ")
                    leg["prob"] = pct / 100
            else:
                pct = _prompt_float("    Enter probability % (e.g. 65): ")
                leg["prob"] = pct / 100

        elif leg_type == "spread":
            leg["team"]   = input("    Team covering: ").strip()
            leg["spread"] = input("    Spread (e.g. -5.5): ").strip()
            leg["odds"]   = _prompt_int("    Odds (American, e.g. -110): ")
            pct           = _prompt_float("    Enter probability % (e.g. 58): ")
            leg["prob"]   = pct / 100

        legs.append(leg)
        print(f"    ✅ Added: {_leg_label(leg)} ({round(leg['prob']*100,1)}%)\n")

    if not legs:
        print("  No legs entered.\n")
        return

    print("\n" + "="*55)
    print("  Evaluating...\n")
    result = evaluate_parlay(legs)
    print(result["summary"])

    save = input("\n  Save full JSON report? (y/n): ").strip().lower()
    if save == "y":
        fname = "parlay_report.json"
        with open(fname, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  Saved to {fname}")

    print()


def _prompt_float(msg: str) -> float:
    while True:
        try:
            return float(input(msg).strip())
        except ValueError:
            print("    Please enter a number.")


def _prompt_int(msg: str) -> int | None:
    val = input(msg).strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


# ─────────────────────────────────────────────
# QUICK EVAL — non-interactive
# ─────────────────────────────────────────────

def quick_eval(legs: list, print_output: bool = True) -> dict:
    """
    Non-interactive version for use in other scripts.

    Example:
        result = quick_eval([
            {"type": "team_ml",     "team": "Las Vegas Aces",
             "opponent": "Minnesota Lynx", "prob": 0.65, "odds": -180},
            {"type": "player_prop", "player": "A'ja Wilson", "team": "Las Vegas Aces",
             "stat": "pts", "line": 22.5, "prob": 0.70, "odds": -115},
        ])
    """
    result = evaluate_parlay(legs)
    if print_output:
        print(result["summary"])
    return result


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--example":
        # Run a sample evaluation
        print("\nRunning example parlay...\n")
        quick_eval([
            {
                "type": "team_ml",
                "team": "Las Vegas Aces",
                "opponent": "Minnesota Lynx",
                "prob": 0.65,
                "odds": -180,
            },
            {
                "type": "player_prop",
                "player": "A'ja Wilson",
                "team": "Las Vegas Aces",
                "stat": "pts",
                "line": 22.5,
                "prob": 0.70,
                "odds": -115,
            },
            {
                "type": "player_prop",
                "player": "Kelsey Plum",
                "team": "Los Angeles Sparks",
                "stat": "pts",
                "line": 20.5,
                "prob": 0.58,
                "odds": -110,
            },
        ])
    else:
        interactive_builder()
