"""
alert_engine.py — Culture & Pulse Analytics
Phase 1: Smarter Alert System with EV + CLV + Bet Quality Rating
"""

from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


# ─────────────────────────────────────────────
# DATA STRUCTURES
# ─────────────────────────────────────────────

@dataclass
class PredictionInput:
    sport: str
    home_team: str
    away_team: str
    game_time: str
    home_win_prob: float
    away_win_prob: float
    bet_team: str
    bet_type: str
    odds: int
    home_net_rating: float
    away_net_rating: float
    opening_odds: Optional[int] = None
    closing_odds: Optional[int] = None
    stake: float = 100.0
    home_injuries: str = ""
    away_injuries: str = ""


@dataclass
class AlertOutput:
    sport: str
    matchup: str
    game_time: str
    bet_team: str
    bet_type: str
    odds: int
    win_probability: float
    implied_probability: float
    ev_per_stake: float
    ev_verdict: str
    bet_quality: str
    star_rating: str
    clv_status: str
    clv_detail: str
    home_net: float
    away_net: float
    model_edge: float
    home_injuries: str
    away_injuries: str
    formatted_slip: str


# ─────────────────────────────────────────────
# CORE CALCULATIONS
# ─────────────────────────────────────────────

def american_to_implied(odds: int) -> float:
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def calculate_ev(win_prob: float, odds: int, stake: float) -> float:
    if odds > 0:
        profit = (odds / 100) * stake
    else:
        profit = (100 / abs(odds)) * stake
    loss_prob = 1 - win_prob
    ev = (win_prob * profit) - (loss_prob * stake)
    return round(ev, 2)


def calculate_clv(opening_odds: Optional[int], closing_odds: Optional[int], our_odds: int) -> tuple:
    if closing_odds is None and opening_odds is None:
        return "NO DATA", "No line movement data available"
    reference_odds = closing_odds if closing_odds is not None else opening_odds
    label = "closing" if closing_odds is not None else "opening"
    our_implied = american_to_implied(our_odds)
    ref_implied = american_to_implied(reference_odds)
    clv_diff = ref_implied - our_implied
    if abs(clv_diff) < 0.005:
        return "AT CLOSE", f"Odds matched the {label} line ({reference_odds:+d})"
    elif clv_diff > 0:
        return "BEAT LINE", f"Got {our_odds:+d} vs {label} {reference_odds:+d} → +{clv_diff*100:.1f}% edge"
    else:
        return "LOST LINE", f"Got {our_odds:+d} vs {label} {reference_odds:+d} → {clv_diff*100:.1f}% edge"


def rate_bet_quality(ev: float, win_prob: float, implied_prob: float, stake: float) -> tuple:
    edge = win_prob - implied_prob
    if ev > 0 and edge > 0.03:
        return "BET IT ✅", "★★★", "POSITIVE"
    elif ev > 0 or (ev < 0 and ev > -(stake * 0.05)):
        return "MARGINAL ⚠️", "★★", "MARGINAL"
    else:
        return "PASS ❌", "★", "NEGATIVE"


# ─────────────────────────────────────────────
# ALERT BUILDER
# ─────────────────────────────────────────────

def build_alert(pred: PredictionInput) -> AlertOutput:
    if pred.bet_team == pred.home_team:
        win_prob = pred.home_win_prob
    else:
        win_prob = pred.away_win_prob

    implied_prob = american_to_implied(pred.odds)
    model_edge   = round((win_prob - implied_prob) * 100, 1)

    ev = calculate_ev(win_prob, pred.odds, pred.stake)
    bet_quality, star_rating, ev_verdict = rate_bet_quality(ev, win_prob, implied_prob, pred.stake)
    clv_status, clv_detail = calculate_clv(pred.opening_odds, pred.closing_odds, pred.odds)

    if pred.odds > 0:
        payout = (pred.odds / 100) * pred.stake
    else:
        payout = (100 / abs(pred.odds)) * pred.stake

    matchup      = f"{pred.away_team} @ {pred.home_team}"
    sport_emoji  = {"NBA": "🏀", "NFL": "🏈", "CFB": "🏈", "WNBA": "🏀"}.get(pred.sport, "🏀")

    # Injury lines for the slip
    home_inj_line = f"  {pred.home_team}: {pred.home_injuries}" if pred.home_injuries else f"  {pred.home_team}: None reported"
    away_inj_line = f"  {pred.away_team}: {pred.away_injuries}" if pred.away_injuries else f"  {pred.away_team}: None reported"

    slip = f"""
{sport_emoji} {pred.sport} ALERT — Culture & Pulse Analytics
{matchup}
🕐 {pred.game_time}

BET: {pred.bet_team} {pred.bet_type} ({pred.odds:+d})
DECISION: {bet_quality} {star_rating}
━━━━━━━━━━━━━━━━━━━━━━━━
EXPECTED VALUE
  EV per ${pred.stake:.0f} stake: ${ev:+.2f} → {ev_verdict}
  Win Probability:  {win_prob*100:.1f}%
  Market Implied:   {implied_prob*100:.1f}%
  Model Edge:       {model_edge:+.1f}%

PAYOUT IF WIN:    +${payout:.0f}
LOSS IF WRONG:    -${pred.stake:.0f}

CLOSING LINE VALUE
  Status: {clv_status}
  {clv_detail}

NET RATINGS
  {pred.home_team}: {pred.home_net_rating:+.1f}
  {pred.away_team}: {pred.away_net_rating:+.1f}

KEY INJURIES
{home_inj_line}
{away_inj_line}
━━━━━━━━━━━━━━━━━━━━━━━━
For entertainment only. Bet responsibly.
""".strip()

    return AlertOutput(
        sport             = pred.sport,
        matchup           = matchup,
        game_time         = pred.game_time,
        bet_team          = pred.bet_team,
        bet_type          = pred.bet_type,
        odds              = pred.odds,
        win_probability   = win_prob,
        implied_probability = implied_prob,
        ev_per_stake      = ev,
        ev_verdict        = ev_verdict,
        bet_quality       = bet_quality,
        star_rating       = star_rating,
        clv_status        = clv_status,
        clv_detail        = clv_detail,
        home_net          = pred.home_net_rating,
        away_net          = pred.away_net_rating,
        model_edge        = model_edge,
        home_injuries     = pred.home_injuries,
        away_injuries     = pred.away_injuries,
        formatted_slip    = slip,
    )


if __name__ == "__main__":
    test = PredictionInput(
        sport="NBA",
        home_team="San Antonio Spurs",
        away_team="New York Knicks",
        game_time="Fri Jun 5 · 07:40 PM CT",
        home_win_prob=0.714,
        away_win_prob=0.286,
        bet_team="New York Knicks",
        bet_type="ML",
        odds=180,
        home_net_rating=-5.2,
        away_net_rating=5.1,
        opening_odds=175,
        closing_odds=None,
        stake=200,
        home_injuries="Keldon Johnson (Questionable)",
        away_injuries="None reported",
    )
    result = build_alert(test)
    print(result.formatted_slip)
