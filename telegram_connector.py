"""
telegram_connector.py — Culture & Pulse Analytics
Sends alert_engine.py output to Telegram.
Includes KEY INJURIES section in each alert.
"""

import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"


def send_message(text: str) -> bool:
    if not TELEGRAM_TOKEN:
        print("  [Telegram] No token found in .env — skipping.")
        return False
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL, "text": text, "parse_mode": "HTML"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            print("  [Telegram] Sent successfully.")
            return True
        else:
            print(f"  [Telegram] Failed: {r.status_code} {r.text}")
            return False
    except Exception as e:
        print(f"  [Telegram] Error: {e}")
        return False


def format_alert(alert) -> str:
    sport_emoji = {
        "NBA": "🏀", "WNBA": "🏀",
        "NFL": "🏈", "CFB": "🏈"
    }.get(alert.sport, "🎯")

    if "BET IT" in alert.bet_quality:
        decision_line = "✅ <b>BET IT</b> ★★★"
    elif "MARGINAL" in alert.bet_quality:
        decision_line = "⚠️ <b>MARGINAL</b> ★★"
    else:
        decision_line = "❌ <b>PASS</b> ★"

    odds_str  = f"+{alert.odds}" if alert.odds > 0 else str(alert.odds)
    ev_str    = f"+${alert.ev_per_stake:.2f}" if alert.ev_per_stake >= 0 else f"-${abs(alert.ev_per_stake):.2f}"
    home_team = alert.matchup.split(" @ ")[1]
    away_team = alert.matchup.split(" @ ")[0]
    home_inj  = alert.home_injuries if alert.home_injuries else "None reported"
    away_inj  = alert.away_injuries if alert.away_injuries else "None reported"
    today     = datetime.now().strftime("%B %d, %Y")

    parts = [
        f"{sport_emoji} <b>{alert.sport} ALERT — Culture &amp; Pulse</b>",
        f"📅 {today}",
        "",
        f"<b>{alert.matchup}</b>",
        f"🕐 {alert.game_time}",
        "",
        f"<b>BET:</b> {alert.bet_team} ML ({odds_str})",
        f"<b>DECISION:</b> {decision_line}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "<b>EXPECTED VALUE</b>",
        f"EV: <b>{ev_str}</b> → {alert.ev_verdict}",
        f"Win Probability: {alert.win_probability*100:.1f}%",
        f"Market Implied: {alert.implied_probability*100:.1f}%",
        f"Model Edge: {alert.model_edge:+.1f}%",
        "",
        "<b>NET RATINGS</b>",
        f"{home_team}: {alert.home_net:+.1f}",
        f"{away_team}: {alert.away_net:+.1f}",
        "",
        "<b>KEY INJURIES</b>",
        f"{home_team}: {home_inj}",
        f"{away_team}: {away_inj}",
        "━━━━━━━━━━━━━━━━━━━━━━━━",
        "<i>Culture &amp; Pulse Analytics</i>",
        "<i>For entertainment only. Bet responsibly.</i>",
    ]
    return "\n".join(parts)


def format_summary(predictions: list, league: str) -> str:
    bet_it   = sum(1 for p in predictions if "BET IT"   in p.bet_quality)
    marginal = sum(1 for p in predictions if "MARGINAL" in p.bet_quality)
    passed   = sum(1 for p in predictions if "PASS"     in p.bet_quality)
    today    = datetime.now().strftime("%B %d, %Y")
    emoji    = "🏀" if league in ("NBA", "WNBA") else "🏈"
    parts = [
        f"{emoji} <b>Culture &amp; Pulse Daily Edge Report</b>",
        f"📅 {today} — {league}",
        "",
        f"Games analyzed: {len(predictions)}",
        f"✅ BET IT: {bet_it}",
        f"⚠️ MARGINAL: {marginal}",
        f"❌ PASS: {passed}",
        "",
        "Full slate below 👇",
    ]
    return "\n".join(parts)


def send_predictions(predictions: list, league: str, bet_it_only: bool = False):
    if not predictions:
        return
    to_send = [p for p in predictions if "BET IT" in p.bet_quality] if bet_it_only else predictions
    if not to_send:
        print(f"  [Telegram] No BET IT alerts to send for {league}.")
        return
    send_message(format_summary(predictions, league))
    time.sleep(1)
    for alert in to_send:
        msg = format_alert(alert)
        send_message(msg)
        time.sleep(1)
    print(f"  [Telegram] Sent {len(to_send)} alerts for {league}.")


if __name__ == "__main__":
    print("Testing Telegram connection...")
    now = datetime.now().strftime("%B %d, %Y %I:%M %p")
    result = send_message(
        "🏀 <b>Culture &amp; Pulse Analytics</b>\n\n"
        "✅ Telegram connector is working.\n"
        f"📅 {now}"
    )
    if result:
        print("Check your Telegram channel.")
    else:
        print("Check your TELEGRAM_TOKEN in .env")
