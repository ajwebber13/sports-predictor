"""
telegram_connector.py — Culture & Pulse Analytics
Sends new alert_engine.py output to Telegram.

Reads TELEGRAM_TOKEN from .env automatically.
Plugs into nba_wnba_predict.py and run_daily.py.

Usage (standalone test):
  python telegram_connector.py
"""

import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load .env from project folder
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"


# ─────────────────────────────────────────────
# SEND
# ─────────────────────────────────────────────

def send_message(text: str) -> bool:
    if not TELEGRAM_TOKEN:
        print("  [Telegram] No token found in .env — skipping.")
        return False

    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHANNEL,
        "text":       text,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print(f"  [Telegram] Sent successfully.")
            return True
        else:
            print(f"  [Telegram] Failed: {r.status_code} {r.text}")
            return False
    except Exception as e:
        print(f"  [Telegram] Error: {e}")
        return False


# ─────────────────────────────────────────────
# FORMAT
# ─────────────────────────────────────────────

def format_alert(alert) -> str:
    """
    Takes an AlertOutput object from alert_engine.py
    and returns a Telegram-formatted HTML string.
    """
    sport_emoji = {
        "NBA": "🏀", "WNBA": "🏀",
        "NFL": "🏈", "CFB": "🏈"
    }.get(alert.sport, "🎯")

    # Decision icon
    if "BET IT" in alert.bet_quality:
        decision_line = f"✅ <b>BET IT</b> ★★★"
    elif "MARGINAL" in alert.bet_quality:
        decision_line = f"⚠️ <b>MARGINAL</b> ★★"
    else:
        decision_line = f"❌ <b>PASS</b> ★"

    # Odds formatting
    odds_str = f"+{alert.odds}" if alert.odds > 0 else str(alert.odds)

    # EV formatting
    ev_str = f"+${alert.ev_per_stake:.2f}" if alert.ev_per_stake >= 0 else f"-${abs(alert.ev_per_stake):.2f}"

    # CLV line
    clv_line = f"{alert.clv_status} — {alert.clv_detail}"

    msg = (
        f"{sport_emoji} <b>{alert.sport} ALERT — Culture &amp; Pulse</b>\n"
        f"📅 {datetime.now().strftime('%B %d, %Y')}\n\n"
        f"<b>{alert.matchup}</b>\n"
        f"🕐 {alert.game_time}\n\n"
        f"<b>BET:</b> {alert.bet_team} ML ({odds_str})\n"
        f"<b>DECISION:</b> {decision_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>EXPECTED VALUE</b>\n"
        f"EV: <b>{ev_str}</b> → {alert.ev_verdict}\n"
        f"Win Probability: {alert.win_probability*100:.1f}%\n"
        f"Market Implied: {alert.implied_probability*100:.1f}%\n"
        f"Model Edge: {alert.model_edge:+.1f}%\n\n"
        f"<b>LINE MOVEMENT</b>\n"
        f"{clv_line}\n\n"
        f"<b>NET RATINGS</b>\n"
        f"{alert.matchup.split(' @ ')[1]}: {alert.home_net:+.1f}\n"
        f"{alert.matchup.split(' @ ')[0]}: {alert.away_net:+.1f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Powered by Culture &amp; Pulse Analytics</i>\n"
        f"<i>For entertainment only. Bet responsibly.</i>"
    )
    return msg


def format_summary(predictions: list, league: str) -> str:
    """Daily summary header sent before individual slips."""
    bet_it   = sum(1 for p in predictions if "BET IT"   in p.bet_quality)
    marginal = sum(1 for p in predictions if "MARGINAL" in p.bet_quality)
    passed   = sum(1 for p in predictions if "PASS"     in p.bet_quality)
    today    = datetime.now().strftime("%B %d, %Y")
    emoji    = "🏀" if league in ("NBA", "WNBA") else "🏈"

    return (
        f"{emoji} <b>Culture &amp; Pulse Daily Edge Report</b>\n"
        f"📅 {today} — {league}\n\n"
        f"Games analyzed: {len(predictions)}\n"
        f"✅ BET IT: {bet_it}\n"
        f"⚠️ MARGINAL: {marginal}\n"
        f"❌ PASS: {passed}\n\n"
        f"Full slate below 👇"
    )


# ─────────────────────────────────────────────
# MAIN SEND FUNCTION
# ─────────────────────────────────────────────

def send_predictions(predictions: list, league: str, bet_it_only: bool = False):
    """
    Call this from nba_wnba_predict.py or run_daily.py.

    predictions = list of AlertOutput objects
    league      = "NBA", "WNBA", "NFL", "CFB"
    bet_it_only = True to only send BET IT alerts (reduces noise)
    """
    if not predictions:
        return

    # Filter if needed
    to_send = [p for p in predictions if "BET IT" in p.bet_quality] if bet_it_only else predictions

    if not to_send:
        print(f"  [Telegram] No BET IT alerts to send for {league}.")
        return

    # Send summary header first
    send_message(format_summary(predictions, league))
    time.sleep(1)

    # Send each alert
    for alert in to_send:
        msg = format_alert(alert)
        send_message(msg)
        time.sleep(1)

    print(f"  [Telegram] Sent {len(to_send)} alerts for {league}.")


# ─────────────────────────────────────────────
# TEST
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("Testing Telegram connection...")
    result = send_message(
        "🏀 <b>Culture &amp; Pulse Analytics</b>\n\n"
        "✅ Telegram connector is working.\n"
        f"📅 {datetime.now().strftime('%B %d, %Y %I:%M %p')}"
    )
    if result:
        print("Check your Telegram channel.")
    else:
        print("Check your TELEGRAM_TOKEN in .env")
