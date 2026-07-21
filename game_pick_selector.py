"""
game_pick_selector.py

Cuts the noise on game picks: evaluates Moneyline, Spread, and Total
independently per game and only surfaces the market(s) that clear your
threshold.

Rule (per Drew's spec, 2026-07-19):
- Check ML, Spread, Total edges for each game independently
- If 1 market clears the threshold -> show that one
- If 2+ clear it -> show up to 2, ranked by edge size (highest first)
- If 0 clear it -> the game does not appear at all

REWRITTEN (2026-07-20, Prediction Engine v2): the /wnba/edges, /mlb/edges,
/cfb/edges, /nfl/edges routes no longer return one combined row per game
with spread/total data tacked on as extra fields (posted_spread,
spread_pick, spread_edge, projected_total, posted_total, over_prob,
under_prob). They now return up to 3 SEPARATE rows per game — one per
market — each already carrying its own market/pick/line/model_prob/edge
fields directly:

    {"game": ..., "market": "moneyline"|"spread"|"total",
     "bet": "Team ML" | "Team +1.5" | "Over 158.5",
     "pick": ..., "line": ...,
     "model_prob": <confidence in THIS specific pick, 0-100>,
     "edge": <decimal fraction, e.g. 0.081 = 8.1%>,
     "odds": ..., "projected": ...}

This is true for every sport now, including MLB — the old "MLB is
moneyline-only, spread_pick/spread_edge never present" restriction is
gone along with the field shape it was written around. extract_markets()
below is now a thin adapter (mostly just re-labeling), since the routes
already do the real per-market extraction work that used to happen here.

Edge thresholds are now uniformly PERCENTAGE-based (edge * 100) for
every market, matching what the routes already compute and gate on
internally (their own min_edge query param). The old point-based
thresholds (MIN_SPREAD_EDGE_PTS, MIN_TOTAL_EDGE_PTS) don't match this
shape anymore — replaced with MIN_SPREAD_EDGE_PCT/MIN_TOTAL_EDGE_PCT
below. These are a reasonable starting default (matching the routes'
own 3.0% floor with a bit of headroom, same relationship the old
MIN_EDGE_PCT=5.0 had to a typical 3.0% API floor) — adjust if you want
spread/total held to a different bar than moneyline.
"""

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Thresholds — all percentage-based now (edge * 100), applied on TOP of
# whatever min_edge the /edges route itself already filtered on.
# ---------------------------------------------------------------------------
MIN_EDGE_PCT = {
    "wnba": 5.0,
    "mlb": 5.0,
    "cfb": 5.0,
    "nfl": 5.0,
}
MIN_SPREAD_EDGE_PCT = 5.0
MIN_TOTAL_EDGE_PCT = 5.0


@dataclass
class MarketPick:
    market: str            # "moneyline" | "spread" | "total"
    team_or_side: str      # e.g. "Las Vegas Aces ML" or "Over 158.5"
    win_prob: Optional[float]    # 0-100 scale — confidence in THIS pick specifically
    edge_value: float             # percent (all markets, as of this rewrite)
    edge_display: str
    odds: Optional[str]
    projected: Optional[str]
    ai_reasoning: Optional[str] = None


def extract_markets(sport: str, raw_row: dict) -> list[MarketPick]:
    """Adapter over ONE row from /​<sport>/edges — each row is already a
    single market (moneyline, spread, or total) as of Prediction Engine
    v2, so this just reads it directly instead of pulling multiple
    markets out of one combined row the way it used to."""
    market = raw_row.get("market", "moneyline")
    bet_label = raw_row.get("bet")
    if not bet_label:
        return []

    edge_pct = round(raw_row.get("edge", 0) * 100, 1)
    return [MarketPick(
        market=market,
        team_or_side=bet_label,
        win_prob=raw_row.get("model_prob"),
        edge_value=edge_pct,
        edge_display=f"+{edge_pct}%",
        odds=raw_row.get("odds"),
        projected=raw_row.get("projected"),
    )]


def _clears_threshold(sport: str, pick: MarketPick) -> bool:
    if pick.market == "moneyline":
        return pick.edge_value >= MIN_EDGE_PCT.get(sport, 5.0)
    if pick.market == "spread":
        return pick.edge_value >= MIN_SPREAD_EDGE_PCT
    if pick.market == "total":
        return pick.edge_value >= MIN_TOTAL_EDGE_PCT
    return False


def get_daily_game_picks(sport: str, raw_games: list[dict]) -> list[dict]:
    """
    `raw_games` = the `best_bets` list straight from /​<sport>/edges.
    Each row is one market for one game (Prediction Engine v2) — a
    game can appear 1-3 times (moneyline, spread, total), which is why
    this groups by the `game` label before picking the top qualifying
    markets, same as before this rewrite.
    """
    grouped: dict[str, list[dict]] = {}
    for raw_row in raw_games:
        grouped.setdefault(raw_row.get("game", ""), []).append(raw_row)

    results = []
    for game_label, rows in grouped.items():
        all_candidates: list[MarketPick] = []
        for row in rows:
            all_candidates.extend(extract_markets(sport, row))

        qualifying = [p for p in all_candidates if _clears_threshold(sport, p)]
        qualifying.sort(key=lambda p: p.edge_value, reverse=True)
        qualifying = qualifying[:2]

        if not qualifying:
            continue

        results.append({
            "game": game_label,
            "sport": sport,
            "picks": qualifying,
        })

    return results


if __name__ == "__main__":
    # smoke test using the REAL multi-row shape from routes_wnba.py
    fake_wnba_rows = [
        {"game": "Chicago Sky @ Las Vegas Aces", "market": "moneyline",
         "bet": "Las Vegas Aces ML", "pick": "Las Vegas Aces", "line": None,
         "model_prob": 64.0, "edge": 0.123, "odds": -175, "projected": "82.1-74.6"},
        {"game": "Chicago Sky @ Las Vegas Aces", "market": "spread",
         "bet": "Las Vegas Aces -6.5", "pick": "Las Vegas Aces", "line": -6.5,
         "model_prob": 58.2, "edge": 0.058, "odds": -110, "projected": "82.1-74.6"},
        {"game": "Chicago Sky @ Las Vegas Aces", "market": "total",
         "bet": "Over 158.5", "pick": "Over", "line": 158.5,
         "model_prob": 54.0, "edge": 0.016, "odds": -110, "projected": "82.1-74.6"},
    ]

    daily_picks = get_daily_game_picks("wnba", fake_wnba_rows)
    for g in daily_picks:
        print(g["game"])
        for p in g["picks"]:
            print(f"  [{p.market}] {p.team_or_side} ({p.edge_display})")

    # MLB smoke test — now CAN show spread/total, not restricted to ML
    fake_mlb_rows = [
        {"game": "Padres @ Dodgers", "market": "moneyline",
         "bet": "Dodgers ML", "pick": "Dodgers", "line": None,
         "model_prob": 61.0, "edge": 0.07, "odds": -140, "projected": "5-3"},
        {"game": "Padres @ Dodgers", "market": "spread",
         "bet": "Dodgers -1.5", "pick": "Dodgers", "line": -1.5,
         "model_prob": 59.0, "edge": 0.066, "odds": -130, "projected": "5-3"},
    ]
    print("\nMLB:")
    for g in get_daily_game_picks("mlb", fake_mlb_rows):
        print(g["game"])
        for p in g["picks"]:
            print(f"  [{p.market}] {p.team_or_side} ({p.edge_display})")