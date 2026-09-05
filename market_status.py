"""
market_status.py

Single source of truth for which sport+market combos are safe to display.
Dashboard code should NEVER hardcode a sport or market check — it reads
get_status() from here instead.

Statuses:
  LIVE  - proven via calibration_audit.py, safe to show confidence %
  WATCH - showing picks, but confidence hidden or labeled "beta/uncalibrated"
  OFF   - not shown at all

Promotion rule (manual, not automatic):
  A market moves WATCH -> LIVE only when BOTH are true, checked by hand
  via calibration_audit.py --by-market:
    1. MIN_GRADED_PICKS graded picks exist for that sport+market
    2. ECE for that band is below MAX_ECE_FOR_LIVE

  Never auto-promote. Run the audit, confirm both numbers, then flip
  the status below and commit.
"""

MIN_GRADED_PICKS = 50
MAX_ECE_FOR_LIVE = 0.15

# sport -> market -> status
MARKET_STATUS = {
    "wnba": {
        "moneyline": "LIVE",   # confirmed 2026-09-02: Brier 0.2152, ECE 0.079
        "spread":    "WATCH",  # ECE ~0.24, not close
        "total":     "WATCH",  # ECE ~0.26, not close
    },
    "cfb": {
        "moneyline": "WATCH",  # 0 graded picks this season yet
        "spread":    "WATCH",
        "total":     "WATCH",
    },
    "nfl": {
        "moneyline": "WATCH",  # 0 graded picks this season yet
        "spread":    "WATCH",
        "total":     "WATCH",
    },
    "mlb": {
        "moneyline": "OFF",    # props and game picks both shelved
        "spread":    "OFF",
        "total":     "OFF",
    },
}


def get_status(sport: str, market: str) -> str:
    """Returns LIVE / WATCH / OFF for a sport+market. Defaults to OFF
    if the sport or market isn't configured, so an unknown combo never
    accidentally shows up live."""
    return MARKET_STATUS.get(sport, {}).get(market, "OFF")


def show_confidence(sport: str, market: str) -> bool:
    """Dashboard calls this before rendering a % badge. Only LIVE shows
    a real number — WATCH and OFF never display a confidence figure."""
    return get_status(sport, market) == "LIVE"


def is_visible(sport: str, market: str) -> bool:
    """Dashboard calls this before rendering the pick row at all."""
    return get_status(sport, market) in ("LIVE", "WATCH")
