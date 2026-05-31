"""
telegram_alerts.py
===================
Sends edge alerts to the Culture & Pulse Telegram channel.
Run manually or schedule weekly via Task Scheduler.

Usage:
  python telegram_alerts.py --sport ncaaf
  python telegram_alerts.py --sport nfl
"""

import requests
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'services'))

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"
API_BASE         = "http://127.0.0.1:8000"


# ─────────────────────────────────────────────────────────────
# SEND MESSAGE
# ─────────────────────────────────────────────────────────────

def send_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL,
        "text": text,
        "parse_mode": "HTML",
    }
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("Sent successfully")
    else:
        print(f"Failed: {r.status_code} {r.text}")


# ─────────────────────────────────────────────────────────────
# FORMAT ALERT
# ─────────────────────────────────────────────────────────────

def edge_stars(edge_pct: float) -> str:
    if edge_pct >= 8:   return "★★★ STRONG"
    if edge_pct >= 5:   return "★★ MODERATE"
    return "★ SLIGHT"

def format_odds(odds: int) -> str:
    if odds > 0: return f"+{odds}"
    return str(odds)

def format_alert(bet: dict, sport: str) -> str:
    edge_pct    = round(bet.get("edge", 0) * 100, 1)
    model_prob  = bet.get("model_prob", 0)
    implied     = bet.get("implied_prob", 0)
    cover       = bet.get("cover_prob", "N/A")
    confidence  = bet.get("confidence", "N/A")
    game        = bet.get("game", "")
    bet_label   = bet.get("bet", "")
    odds        = bet.get("odds", -110)
    spread      = bet.get("spread_line", "N/A")
    epa_off     = bet.get("epa_off", 0)
    epa_def     = bet.get("epa_def", 0)
    stars       = edge_stars(edge_pct)
    sport_emoji = "🏈" if sport in ["ncaaf", "nfl"] else "🏀"
    league      = sport.upper()

    # Parse team names from game string "Away @ Home"
    parts = game.split(" @ ")
    away  = parts[0] if len(parts) == 2 else ""
    home  = parts[1] if len(parts) == 2 else ""

    msg = f"""{sport_emoji} <b>EDGE ALERT — {league}</b>

<b>{game}</b>

MODEL EDGE: <b>+{edge_pct}% {stars}</b>
━━━━━━━━━━━━━━━━━━━━━━━━
<b>Bet:</b> {bet_label} ({format_odds(odds)})
<b>Spread:</b> {spread} | <b>Cover Prob:</b> {cover}%

<b>WIN PROBABILITY</b>
{away if away else "Away"}: {round(100 - model_prob, 1)}%
{home if home else "Home"}: {model_prob}%
Market implied: {implied}%

<b>ADVANCED STATS</b>
EPA Offense: {epa_off:+.3f}
EPA Defense: {epa_def:+.3f}

<b>CONFIDENCE:</b> {confidence}
━━━━━━━━━━━━━━━━━━━━━━━━
<i>Powered by Culture &amp; Pulse Analytics</i>
<i>For entertainment only. Bet responsibly.</i>"""

    return msg


# ─────────────────────────────────────────────────────────────
# HEADER + SUMMARY
# ─────────────────────────────────────────────────────────────

def format_header(bets: list, sport: str) -> str:
    sport_emoji = "🏈" if sport in ["ncaaf", "nfl"] else "🏀"
    top_edge = max((b.get("edge", 0) * 100 for b in bets), default=0)
    return f"""{sport_emoji} <b>Culture &amp; Pulse Weekly Edge Report</b>
<b>Sport:</b> {sport.upper()}
<b>Edges found:</b> {len(bets)}
<b>Top edge:</b> +{round(top_edge, 1)}%

Full slate below 👇"""


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run_alerts(sport: str = "ncaaf", simulations: int = 10000):
    print(f"Fetching edges for {sport}...")

    try:
        r = requests.get(
            f"{API_BASE}/edges",
            params={"sport": sport, "simulations": simulations},
            timeout=60,
        )
        data = r.json()
    except Exception as e:
        print(f"Could not reach FastAPI: {e}")
        print("Make sure uvicorn is running: python -m uvicorn app.main:app")
        return

    bets = data.get("best_bets", [])

    if not bets:
        print("No edges found above threshold.")
        send_message(f"🏈 <b>C&amp;P Edge Report — {sport.upper()}</b>\n\nNo edges above threshold this week. Stay patient.")
        return

    # Send header
    send_message(format_header(bets, sport))

    # Send each edge as a separate message
    for bet in bets:
        msg = format_alert(bet, sport)
        send_message(msg)
        import time; time.sleep(1)  # avoid rate limiting

    print(f"Sent {len(bets)} alerts to {TELEGRAM_CHANNEL}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="ncaaf", help="Sport: ncaaf, nfl, nba")
    parser.add_argument("--sims", type=int, default=10000, help="Simulations per game")
    args = parser.parse_args()
    run_alerts(sport=args.sport, simulations=args.sims)
