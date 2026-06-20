"""
kelly.py — Culture & Pulse Analytics
======================================
Kelly Criterion stake sizing for sports picks.

Full Kelly is mathematically optimal but too aggressive for real betting.
We use fractional Kelly (default 0.5 = half-Kelly) which cuts variance
significantly while preserving most of the edge.

Formula:
  Kelly % = (edge / decimal_odds_profit)
  where edge = win_prob - implied_prob

Usage:
  from kelly import kelly_stake, format_kelly_line
  stake_pct, units, verdict = kelly_stake(win_prob=0.72, odds=-110, edge_pct=15.2)
"""


# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

KELLY_FRACTION  = 0.5    # half-Kelly — reduces variance, standard practice
MAX_KELLY_PCT   = 5.0    # never suggest more than 5% of bankroll per bet
MIN_KELLY_PCT   = 0.5    # below this, not worth sizing — pass
DEFAULT_BANKROLL = 1000  # default bankroll for unit display


# ─────────────────────────────────────────────────────────────
# CORE MATH
# ─────────────────────────────────────────────────────────────

def american_to_decimal(odds: int) -> float:
    """Convert American odds to decimal profit per 1 unit staked."""
    if odds > 0:
        return odds / 100.0
    else:
        return 100.0 / abs(odds)


def american_to_implied(odds: int) -> float:
    """Convert American odds to implied probability."""
    if odds > 0:
        return 100 / (odds + 100)
    return abs(odds) / (abs(odds) + 100)


def kelly_stake(
    win_prob: float,
    odds: int,
    edge_pct: float,
    bankroll: float = DEFAULT_BANKROLL,
    fraction: float = KELLY_FRACTION,
) -> tuple:
    """
    Calculate Kelly stake size.

    Args:
        win_prob:   Model win probability (0-1 or 0-100, auto-detected)
        odds:       American odds (e.g. -110, +150)
        edge_pct:   Model edge in percentage (e.g. 15.2)
        bankroll:   Total bankroll in dollars
        fraction:   Kelly fraction (0.5 = half-Kelly)

    Returns:
        (kelly_pct, stake_dollars, verdict)
        kelly_pct:      Suggested % of bankroll
        stake_dollars:  Suggested dollar amount
        verdict:        Human-readable sizing label
    """
    # Normalize win_prob to 0-1
    if win_prob > 1:
        win_prob = win_prob / 100.0

    # Edge must be positive to bet
    edge = edge_pct / 100.0
    if edge <= 0:
        return 0.0, 0.0, "NO BET — negative edge"

    # Decimal profit per unit staked
    decimal_odds = american_to_decimal(odds)

    # Full Kelly formula: f = edge / decimal_odds
    full_kelly = edge / decimal_odds

    # Apply fraction (half-Kelly by default)
    fractional_kelly = full_kelly * fraction

    # Cap and floor
    kelly_pct = round(min(max(fractional_kelly * 100, 0), MAX_KELLY_PCT), 2)

    if kelly_pct < MIN_KELLY_PCT:
        return kelly_pct, 0.0, "PASS — edge too thin to size"

    stake_dollars = round(bankroll * (kelly_pct / 100), 2)

    # Verdict label
    if kelly_pct >= 3.0:
        verdict = f"★★★ SIZE UP — {kelly_pct:.1f}% of bankroll"
    elif kelly_pct >= 1.5:
        verdict = f"★★ STANDARD — {kelly_pct:.1f}% of bankroll"
    else:
        verdict = f"★ SMALL — {kelly_pct:.1f}% of bankroll"

    return kelly_pct, stake_dollars, verdict


def format_kelly_line(
    win_prob: float,
    odds: int,
    edge_pct: float,
    bankroll: float = DEFAULT_BANKROLL,
) -> str:
    """
    Returns a formatted Kelly line for the Telegram alert.

    Example output:
      💰 Kelly Stake: 2.3% → $23 on $1,000 bankroll (half-Kelly)
    """
    kelly_pct, stake_dollars, verdict = kelly_stake(win_prob, odds, edge_pct, bankroll)

    if kelly_pct < MIN_KELLY_PCT:
        return f"💰 <b>Kelly:</b> <i>Edge too thin — skip or minimum stake only</i>"

    return (
        f"💰 <b>Kelly Stake:</b> {kelly_pct:.1f}% → "
        f"${stake_dollars:,.0f} on ${bankroll:,.0f} bankroll "
        f"<i>(half-Kelly)</i>"
    )


def kelly_summary_table(picks: list, bankroll: float = DEFAULT_BANKROLL) -> str:
    """
    Builds a Kelly summary table for the slate summary message.
    picks: list of dicts with keys: game, bet, win_prob, odds, edge_pct
    """
    if not picks:
        return ""

    lines = ["\n💰 <b>Kelly Sizing Guide</b>"]
    lines.append(f"<i>Bankroll: ${bankroll:,.0f} | Half-Kelly</i>\n")

    total_exposure = 0.0
    for p in picks:
        win_prob = p.get("win_prob", 0.6)
        odds     = p.get("odds", -110)
        edge_pct = p.get("edge_pct", 8.0)
        bet      = p.get("bet", "")
        game     = p.get("game", "")

        if isinstance(odds, str):
            try:
                odds = int(odds)
            except:
                odds = -110

        kelly_pct, stake, verdict = kelly_stake(win_prob, odds, edge_pct, bankroll)
        total_exposure += kelly_pct

        short_game = game.split(" @ ")[-1] if " @ " in game else game
        lines.append(
            f"  {short_game} — {bet}\n"
            f"  {kelly_pct:.1f}% → ${stake:,.0f}  {verdict.split('—')[0].strip()}\n"
        )

    lines.append(f"<i>Total exposure: {total_exposure:.1f}% of bankroll</i>")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# ENTRY POINT — self test
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n── Kelly Criterion Test ──\n")

    test_picks = [
        {"game": "Minnesota Lynx @ Atlanta Dream",       "bet": "Atlanta Dream ML",     "win_prob": 0.72, "odds": -130, "edge_pct": 15.2},
        {"game": "Las Vegas Aces @ New York Liberty",    "bet": "New York Liberty ML",  "win_prob": 0.68, "odds": -110, "edge_pct": 12.1},
        {"game": "Seattle Storm @ Indiana Fever",        "bet": "Indiana Fever ML",     "win_prob": 0.66, "odds": -115, "edge_pct": 9.4},
    ]

    bankroll = 1000

    for pick in test_picks:
        pct, stake, verdict = kelly_stake(
            pick["win_prob"], pick["odds"], pick["edge_pct"], bankroll
        )
        print(f"  {pick['bet']}")
        print(f"  Edge: {pick['edge_pct']}% | Odds: {pick['odds']} | Win prob: {pick['win_prob']*100:.0f}%")
        print(f"  → {verdict}")
        print(f"  → ${stake:.0f} on ${bankroll} bankroll\n")

    print("── Slate Summary Table ──")
    print(kelly_summary_table(test_picks, bankroll=1000))
