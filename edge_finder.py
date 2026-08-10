"""
edge_finder.py — Culture & Pulse Analytics
============================================
Ranks today's player props by a composite "Edge Score" instead of a
single tier — the Bobby's Bets-style "Top Edges" list.

Reads straight from player_props (already populated by
save_prop_with_hit_rates() + save_projection() for each sport), so this
file does no new data collection — it's a ranking layer on top of data
that already exists.

Composite score = weighted blend of three signals, each min-max
normalized to 0-100 across TODAY'S slate before weighting (same
normalize-then-weight pattern as ranking_engine.py's Power Score, so a
lopsided single stat can't silently dominate):

    hit_rate_overall      40%   (historical: how often this hits)
    |projection_edge_pct| 40%   (forward-looking: how far off the line)
    defense_alignment     20%   (is tonight's opponent matchup favorable
                                  for the direction we're picking?)

defense_alignment direction handling: defense_factor > 1.0 means the
opponent allows MORE than average (good for OVER picks), < 1.0 means
they allow LESS (good for UNDER picks). A raw defense_factor is only
"good" or "bad" once you know which side of the prop you're on, so this
mirrors the factor around 1.0 for "under" picks before normalizing —
otherwise every "under" pick vs a leaky defense would incorrectly score
high.

Rows missing hit_rate_overall, projection_edge_pct, or defense_factor
are excluded rather than backfilled with a guessed neutral value —
same principle as the rest of the engine chain (ranking_engine.py never
invents a number it doesn't have).

CONFIDENCE GUARDRAILS (v1.1): edge_score alone isn't enough to publish
on. A 4-for-5 (80%) hit rate normalizes just as high as a real 40-game
sample — small-sample noise would otherwise rank #1 next to real signal.
MIN_HIT_RATE / MIN_EDGE_PCT / MIN_SAMPLE_SIZE gate what's eligible to
appear at all; CONFIDENCE_HIGH_SCORE / CONFIDENCE_HIGH_SAMPLE gate the
HIGH vs MEDIUM label on picks that do clear the bar.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn, rows_to_dicts as _rows_to_dicts

HIT_RATE_WEIGHT = 0.40
EDGE_PCT_WEIGHT = 0.40
DEFENSE_WEIGHT  = 0.20

# Projection edge % is a raw percentage of the prop line. Low-line props
# (e.g. HITS Over 0.5) mathematically produce huge percentages just from
# a small denominator — that's not stronger signal, it's the line being
# small. Capping before normalization stops these from structurally
# dominating the composite score over higher-line props. Report display
# still shows the real uncapped number.
MAX_EDGE_PCT_FOR_SCORING = 100.0

SUPPORTED_SPORTS = ["wnba", "mlb", "nba", "nfl"]

# --- Confidence guardrails ---
# Eligibility floor — rows failing any of these are dropped before ranking,
# not just scored low. Small-sample hit rates are the main failure mode
# these catch (see module docstring).
MIN_HIT_RATE    = 65.0   # %
MIN_EDGE_PCT    = 5.0    # absolute projection edge %
MIN_SAMPLE_SIZE = 10     # games_overall

# Injury status is a hard exclude when known — a confirmed OUT player
# should never appear regardless of how good their historical numbers
# look. This does NOT require injury_status to be populated (most rows
# won't have it yet) — only excludes rows explicitly marked 'out'.
EXCLUDE_INJURY_STATUSES = ("out",)

# projected_minutes/injury_status aren't required for eligibility (they're
# not backfilled yet) but DO raise the confidence bar once available —
# this rewards picks that have real opportunity context over ones that
# don't, without breaking anything for rows still missing the fields.
CONFIDENCE_REQUIRES_MINUTES = True

# HIGH-confidence label thresholds (on top of the eligibility floor above)
CONFIDENCE_HIGH_SCORE  = 80.0   # edge_score
CONFIDENCE_HIGH_SAMPLE = 15     # games_overall

# Per-sport module + defense-factor function used for the opponent's
# league-wide rank on this stat (e.g. "#24 Defense vs PTS"). Optional —
# only used for the formatted report, never blocks a ranking if it fails.
_DEFENSE_MODULE = {
    "wnba": "wnba_defense_ratings",
    "mlb":  "mlb_defense_ratings",
    "nba":  "nba_defense_ratings",
    "nfl":  "nfl_defense_ratings",
}


def _normalize(values: dict) -> dict:
    """Min-max normalize a {key: value} dict to 0-100. Flat input (all
    same value, or a single row) returns 50 for every key rather than
    dividing by zero."""
    if not values:
        return {}
    lo, hi = min(values.values()), max(values.values())
    if hi == lo:
        return {k: 50.0 for k in values}
    return {k: round((v - lo) / (hi - lo) * 100, 1) for k, v in values.items()}


def _defense_rank(sport: str, stat: str, team: str, direction: str):
    """Returns (rank, total_teams) for how favorable `team`'s defense is
    on `stat`, oriented so #1 = most favorable for `direction`. Returns
    (None, None) on any failure (unmapped stat, module not found, etc.)
    — this is presentation-layer only and never blocks a ranking."""
    module_name = _DEFENSE_MODULE.get(sport)
    if not module_name or not team:
        return None, None
    try:
        mod = __import__(module_name, fromlist=["get_defense_factors"])
        factors = mod.get_defense_factors(stat)
    except Exception:
        return None, None
    if not factors or team not in factors:
        return None, None

    # over favors high factor (weak D), under favors low factor (tough D)
    ordered = sorted(factors.items(), key=lambda kv: kv[1], reverse=(direction == "over"))
    for i, (t, _) in enumerate(ordered, 1):
        if t == team:
            return i, len(ordered)
    return None, None


def get_edge_finder(
    date: str,
    sport: str = "wnba",
    top_n: int = 10,
    min_games: int = MIN_SAMPLE_SIZE,
    min_hit_rate: float = MIN_HIT_RATE,
    min_edge_pct: float = MIN_EDGE_PCT,
) -> list:
    """Returns the top_n props for `date`/`sport` ranked by composite
    Edge Score, highest first. Rows are first filtered by the
    confidence guardrails (min_games/min_hit_rate/min_edge_pct) before
    scoring — the guardrails decide who's even eligible, the score
    decides the order among the eligible. Each item includes the raw
    inputs and a confidence label alongside the score so the reasoning
    is visible, not just the number."""
    if sport not in SUPPORTED_SPORTS:
        return []

    conn = _get_conn()
    c = conn.cursor()
    exclude_placeholders = ",".join("?" for _ in EXCLUDE_INJURY_STATUSES)
    c.execute(f"""
        SELECT player_name, team_name, opponent, stat, line,
               hit_rate_overall, games_overall,
               projection_edge_pct, projection_direction, projection_tier,
               defense_factor, confidence_tier, over_odds, under_odds,
               projected_minutes, injury_status, starter_status,
               opening_over_odds, opening_under_odds
        FROM player_props
        WHERE date = ? AND sport = ?
          AND hit_rate_overall IS NOT NULL
          AND projection_edge_pct IS NOT NULL
          AND defense_factor IS NOT NULL
          AND games_overall >= ?
          AND hit_rate_overall >= ?
          AND ABS(projection_edge_pct) >= ?
          AND (injury_status IS NULL OR injury_status NOT IN ({exclude_placeholders}))
    """, (date, sport, min_games, min_hit_rate, min_edge_pct, *EXCLUDE_INJURY_STATUSES))
    rows = _rows_to_dicts(c, c.fetchall())
    conn.close()

    if not rows:
        return []

    hit_rate_vals = {i: r["hit_rate_overall"] for i, r in enumerate(rows)}
    edge_pct_vals = {
        i: min(abs(r["projection_edge_pct"]), MAX_EDGE_PCT_FOR_SCORING)
        for i, r in enumerate(rows)
    }

    defense_vals = {}
    for i, r in enumerate(rows):
        factor = r["defense_factor"]
        # mirror around 1.0 for "under" picks — see module docstring
        defense_vals[i] = factor if r["projection_direction"] == "over" else (2.0 - factor)

    hit_rate_norm = _normalize(hit_rate_vals)
    edge_pct_norm = _normalize(edge_pct_vals)
    defense_norm  = _normalize(defense_vals)

    ranked = []
    for i, r in enumerate(rows):
        edge_score = round(
            hit_rate_norm[i] * HIT_RATE_WEIGHT +
            edge_pct_norm[i] * EDGE_PCT_WEIGHT +
            defense_norm[i]  * DEFENSE_WEIGHT,
            1
        )
        has_minutes = r.get("projected_minutes") is not None
        confidence = (
            "HIGH" if edge_score >= CONFIDENCE_HIGH_SCORE
                      and r["games_overall"] >= CONFIDENCE_HIGH_SAMPLE
                      and (has_minutes or not CONFIDENCE_REQUIRES_MINUTES)
            else "MEDIUM"
        )
        ranked.append({
            **r,
            "edge_score": edge_score,
            "confidence": confidence,
            "edge_score_components": {
                "hit_rate_norm": hit_rate_norm[i],
                "edge_pct_norm": edge_pct_norm[i],
                "defense_norm": defense_norm[i],
            },
        })

    ranked.sort(key=lambda x: x["edge_score"], reverse=True)
    return ranked[:top_n]


def print_debug_report(date: str, sport: str = "wnba", top_n: int = 10, **guardrail_overrides):
    """Prints the per-player score breakdown so a ranking can be
    audited before it's trusted — 'why is this #1' should always be
    answerable from this output alone."""
    picks = get_edge_finder(date, sport=sport, top_n=top_n, **guardrail_overrides)
    if not picks:
        print(f"No qualifying edges for {sport.upper()} on {date} "
              f"(check guardrail thresholds or whether props exist for this date).")
        return

    for p in picks:
        comp = p["edge_score_components"]
        direction_label = "Over" if p["projection_direction"] == "over" else "Under"
        print(f"Player: {p['player_name']}")
        print(f"Prop: {p['stat'].upper()} {direction_label} {p['line']}")
        print(f"Hit Rate:")
        print(f"  {p['hit_rate_overall']}% ({p['games_overall']}G) -> normalized {comp['hit_rate_norm']}")
        print(f"Edge:")
        print(f"  {p['projection_edge_pct']:+.1f}% -> normalized {comp['edge_pct_norm']}")
        print(f"Defense:")
        print(f"  factor {p['defense_factor']} -> normalized {comp['defense_norm']}")
        if p.get("projected_minutes") is not None:
            print(f"Volume: {p['projected_minutes']} projected minutes/volume")
        if p.get("injury_status"):
            print(f"Injury: {p['injury_status']}")
        if p.get("opening_over_odds") is not None and p.get("over_odds") is not None:
            moved = p["over_odds"] - p["opening_over_odds"]
            print(f"Line movement (over): {p['opening_over_odds']:+d} -> {p['over_odds']:+d} ({moved:+d})")
        print(f"Final Edge Score:")
        print(f"  {p['edge_score']}  ({p['confidence']} confidence)")
        print()


def format_edge_finder_report(date: str, sport: str = "wnba", top_n: int = 5, **guardrail_overrides) -> str:
    """Publish-ready 'Top Edges Today' report — the daily Culture & Pulse
    content format. Guardrails are applied before this ever sees the
    rows, so nothing here needs its own small-sample check."""
    picks = get_edge_finder(date, sport=sport, top_n=top_n, **guardrail_overrides)
    if not picks:
        return f"No qualifying edges for {sport.upper()} on {date}."

    lines = [f"🔥 EDGE FINDER — {sport.upper()} TODAY\n"]
    for i, p in enumerate(picks, 1):
        direction_label = "Over" if p["projection_direction"] == "over" else "Under"
        rank, total = _defense_rank(sport, p["stat"], p["opponent"], p["projection_direction"])
        matchup = f"#{rank}/{total} Defense vs {p['stat'].upper()}" if rank else f"vs {p['opponent']}"

        # Same cap already used for scoring (MAX_EDGE_PCT_FOR_SCORING) —
        # applied here too so the DISPLAYED number matches what actually
        # drove the Edge Score. Uncapped, a low-line prop (e.g. HITS
        # Over 0.5) shows a misleadingly huge percentage purely from a
        # small denominator, not real signal.
        capped_edge_pct = max(-MAX_EDGE_PCT_FOR_SCORING,
                               min(MAX_EDGE_PCT_FOR_SCORING, p["projection_edge_pct"]))

        lines.append(f"{i}. {p['player_name']} {p['stat'].upper()} {direction_label} {p['line']}")
        lines.append(f"Edge Score: {p['edge_score']}")
        lines.append(f"✅ Hit Rate: {p['hit_rate_overall']}% ({p['games_overall']}G)")
        lines.append(f"📈 Projection Edge: {capped_edge_pct:+.1f}%")
        lines.append(f"🛡️ Matchup: {matchup}")
        if p.get("injury_status") and p["injury_status"] != "active":
            lines.append(f"⚠️ Status: {p['injury_status']}")
        lines.append(f"Confidence: {p['confidence']}")
        lines.append("")

    return "\n".join(lines).rstrip()


def log_edge_finder_picks(date: str, sport: str, picks: list) -> int:
    """Records picks to edge_finder_picks — one immutable row per pick,
    capturing the edge_score/confidence AS OF the moment it was sent.
    Deliberately separate from player_props, which gets overwritten as
    the day's projections change; results tracking needs to compare
    against what was actually claimed at pick time, not a number that
    could have drifted since.

    ON CONFLICT DO NOTHING (not DO UPDATE) — a pick, once logged, is a
    historical fact. Calling this again for the same (date, sport,
    player, stat) should never silently rewrite what was claimed.

    Callers should only call this for picks that were ACTUALLY SENT
    (e.g. edge_finder_alert.py after a successful, non-dry-run send) —
    never from a dashboard view, API hit, or --dry-run, which recompute
    on demand and would corrupt the tracking history with picks nobody
    ever saw.

    Requires the edge_finder_picks table — see
    edge_finder_picks_schema.sql. Returns the number of picks
    attempted (rows already logged for that date/sport/player/stat are
    silently skipped via ON CONFLICT DO NOTHING, not double-counted —
    but this return value doesn't distinguish new inserts from skips,
    since rowcount behavior isn't guaranteed consistent across the
    Postgres/Turso/SQLite backends this connects to)."""
    if not picks:
        return 0

    conn = _get_conn()
    c = conn.cursor()
    try:
        for p in picks:
            c.execute("""
                INSERT INTO edge_finder_picks
                (date, sport, player_name, stat, line, direction, edge_score, confidence,
                 hit_rate_overall, games_overall, projection_edge_pct, defense_factor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date, sport, player_name, stat) DO NOTHING
            """, (
                date, sport, p["player_name"], p["stat"], p["line"], p["projection_direction"],
                p["edge_score"], p["confidence"], p["hit_rate_overall"], p["games_overall"],
                p["projection_edge_pct"], p["defense_factor"],
            ))
        conn.commit()
    finally:
        conn.close()
    return len(picks)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Rank today's props by composite Edge Score")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--sport", default="wnba", choices=SUPPORTED_SPORTS)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--debug", action="store_true", help="print per-player score breakdown instead of the formatted report")
    parser.add_argument("--min-hit-rate", type=float, default=MIN_HIT_RATE)
    parser.add_argument("--min-edge-pct", type=float, default=MIN_EDGE_PCT)
    parser.add_argument("--min-games", type=int, default=MIN_SAMPLE_SIZE)
    args = parser.parse_args()

    overrides = dict(min_games=args.min_games, min_hit_rate=args.min_hit_rate, min_edge_pct=args.min_edge_pct)

    if args.debug:
        print_debug_report(args.date, sport=args.sport, top_n=args.top, **overrides)
    else:
        print(format_edge_finder_report(args.date, sport=args.sport, top_n=args.top, **overrides))
