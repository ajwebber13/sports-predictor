"""
telegram_alerts.py
===================
Sends edge alerts to the Culture & Pulse Telegram channel.
Run manually or schedule weekly via Task Scheduler.

Usage:
  python telegram_alerts.py --sport ncaaf
  python telegram_alerts.py --sport nfl
  python telegram_alerts.py --sport wnba
  python telegram_alerts.py --sport nba
"""

import requests
import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"
API_BASE         = "https://sports-predictor-api-44a0.onrender.com"

# Central Time offset (CDT = UTC-5, CST = UTC-6)
CENTRAL_OFFSET = -5


# ─────────────────────────────────────────────────────────────
# TIME HELPERS
# ─────────────────────────────────────────────────────────────

def format_game_time(utc_str: str) -> str:
    """Convert UTC ISO string to Central Time display string."""
    try:
        utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        return central_dt.strftime("%a %b %-d · %I:%M %p CT")
    except:
        return "Time TBD"


def get_game_times(sport: str) -> dict:
    """
    Fetch game times from Odds API.
    Returns {game_key: formatted_time} where game_key = 'away @ home'
    """
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    sys.path.insert(0, os.path.join(os.path.abspath("."), "services"))

    try:
        from odds_parser import get_live_odds
        games = get_live_odds(sport)
        times = {}
        for g in games:
            home = g.get("home_team", "")
            away = g.get("away_team", "")
            utc_time = g.get("commence_time", "")
            key = f"{away} @ {home}"
            times[key] = format_game_time(utc_time) if utc_time else "Time TBD"
        return times
    except Exception as e:
        print(f"Could not fetch game times: {e}")
        return {}


# ─────────────────────────────────────────────────────────────
# SEND MESSAGE
# ─────────────────────────────────────────────────────────────

def send_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHANNEL,
        "text":       text,
        "parse_mode": "HTML",
    }
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("Sent successfully")
    else:
        print(f"Failed: {r.status_code} {r.text}")


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def sport_emoji(sport: str) -> str:
    return "🏈" if sport in ["ncaaf", "nfl"] else "🏀"

def edge_stars(edge_pct: float) -> str:
    if edge_pct >= 8:   return "★★★ STRONG"
    if edge_pct >= 5:   return "★★ MODERATE"
    return "★ SLIGHT"

def format_odds(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)


# ─────────────────────────────────────────────────────────────
# FORMAT FOOTBALL ALERT
# ─────────────────────────────────────────────────────────────

def format_football_alert(bet: dict, sport: str, game_time: str = "Time TBD") -> str:
    edge_pct   = round(bet.get("edge", 0) * 100, 1)
    model_prob = bet.get("model_prob", 0)
    implied    = bet.get("implied_prob", 0)
    cover      = bet.get("cover_prob", "N/A")
    confidence = bet.get("confidence", "N/A")
    game       = bet.get("game", "")
    bet_label  = bet.get("bet", "")
    odds       = bet.get("odds", -110)
    epa_off    = bet.get("epa_off", 0)
    epa_def    = bet.get("epa_def", 0)
    stars      = edge_stars(edge_pct)
    emoji      = sport_emoji(sport)
    league     = sport.upper()

    parts = game.split(" @ ")
    away  = parts[0] if len(parts) == 2 else ""
    home  = parts[1] if len(parts) == 2 else ""

    return f"""{emoji} <b>EDGE ALERT — {league}</b>

<b>{game}</b>
🕐 {game_time}

MODEL EDGE: <b>+{edge_pct}% {stars}</b>
━━━━━━━━━━━━━━━━━━━━━━━━
<b>Bet:</b> {bet_label} ({format_odds(odds)})
<b>Cover Prob:</b> {cover}%

<b>WIN PROBABILITY</b>
{away}: {round(100 - model_prob, 1)}%
{home}: {model_prob}%
Market implied: {implied}%

<b>ADVANCED STATS</b>
EPA Offense: {epa_off:+.3f}
EPA Defense: {epa_def:+.3f}

<b>CONFIDENCE:</b> {confidence}
━━━━━━━━━━━━━━━━━━━━━━━━
<i>Powered by Culture &amp; Pulse Analytics</i>
<i>For entertainment only. Bet responsibly.</i>"""


# ─────────────────────────────────────────────────────────────
# FORMAT WNBA ALERT
# ─────────────────────────────────────────────────────────────

def format_wnba_alert(bet: dict, game_time: str = "Time TBD") -> str:
    edge_pct    = round(bet.get("edge", 0) * 100, 1)
    model_prob  = bet.get("model_prob", 0)
    implied     = bet.get("implied_prob", 0)
    bet_label   = bet.get("bet", "")
    game        = bet.get("game", "")
    projected   = bet.get("projected", "N/A")
    home_record = bet.get("home_record", "N/A")
    away_record = bet.get("away_record", "N/A")
    home_rest   = bet.get("home_rest", "N/A")
    away_rest   = bet.get("away_rest", "N/A")
    stars       = edge_stars(edge_pct)

    parts     = game.split(" @ ")
    away_team = parts[0] if len(parts) == 2 else ""
    home_team = parts[1] if len(parts) == 2 else ""

    return f"""🏀 <b>WNBA EDGE ALERT</b>

<b>{game}</b>
🕐 {game_time}

MODEL EDGE: <b>+{edge_pct}% {stars}</b>
━━━━━━━━━━━━━━━━━━━━━━━━
<b>Bet:</b> {bet_label}
<b>Projected Score:</b> {projected}

<b>WIN PROBABILITY</b>
{away_team}: {round(100 - model_prob, 1)}%
{home_team}: {model_prob}%
Market implied: {implied}%

<b>RECORDS &amp; REST</b>
{home_team}: {home_record} | Rest: {home_rest} day(s)
{away_team}: {away_record} | Rest: {away_rest} day(s)
━━━━━━━━━━━━━━━━━━━━━━━━
<i>Powered by Culture &amp; Pulse Analytics</i>
<i>For entertainment only. Bet responsibly.</i>"""


# ─────────────────────────────────────────────────────────────
# FORMAT NBA ALERT
# ─────────────────────────────────────────────────────────────

def format_nba_alert(bet: dict, game_time: str = "Time TBD") -> str:
    edge_pct     = round(bet.get("edge", 0) * 100, 1)
    model_prob   = bet.get("model_prob", 0)
    implied      = bet.get("implied_prob", 0)
    bet_label    = bet.get("bet", "")
    game         = bet.get("game", "")
    odds         = bet.get("odds", -110)
    net_home     = bet.get("net_rating_home", "N/A")
    net_away     = bet.get("net_rating_away", "N/A")
    stars        = edge_stars(edge_pct)

    parts     = game.split(" @ ")
    away_team = parts[0] if len(parts) == 2 else ""
    home_team = parts[1] if len(parts) == 2 else ""

    return f"""🏀 <b>NBA EDGE ALERT</b>

<b>{game}</b>
🕐 {game_time}

MODEL EDGE: <b>+{edge_pct}% {stars}</b>
━━━━━━━━━━━━━━━━━━━━━━━━
<b>Bet:</b> {bet_label} ({format_odds(odds)})

<b>WIN PROBABILITY</b>
{away_team}: {round(100 - model_prob, 1)}%
{home_team}: {model_prob}%
Market implied: {implied}%

<b>NET RATINGS</b>
{home_team}: {net_home:+.1f}
{away_team}: {net_away:+.1f}
━━━━━━━━━━━━━━━━━━━━━━━━
<i>Powered by Culture &amp; Pulse Analytics</i>
<i>For entertainment only. Bet responsibly.</i>"""


# ─────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────

def format_header(bets: list, sport: str) -> str:
    emoji    = sport_emoji(sport)
    top_edge = max((b.get("edge", 0) * 100 for b in bets), default=0)
    today    = datetime.now().strftime("%B %-d, %Y")
    return f"""{emoji} <b>Culture &amp; Pulse Edge Report</b>
📅 {today}
<b>Sport:</b> {sport.upper()}
<b>Edges found:</b> {len(bets)}
<b>Top edge:</b> +{round(top_edge, 1)}%

Full slate below 👇"""


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run_alerts(sport: str = "ncaaf", simulations: int = 10000):
    emoji = sport_emoji(sport)
    print(f"Fetching edges for {sport}...")

    # Get game times first
    import sys, os
    sys.path.insert(0, os.path.abspath("."))
    game_times = get_game_times(sport)
    print(f"Game times found: {len(game_times)}")

    try:
        if sport == "wnba":
            r = requests.get(
                f"{API_BASE}/wnba/edges",
                params={"simulations": simulations},
                timeout=60,
            )
        elif sport == "nba":
            r = requests.get(
                f"{API_BASE}/nba/edges",
                params={"simulations": simulations},
                timeout=60,
            )
        else:
            r = requests.get(
                f"{API_BASE}/edges",
                params={"sport": sport, "simulations": simulations},
                timeout=60,
            )
        data = r.json()
    except Exception as e:
        print(f"Could not reach API: {e}")
        return

    bets = data.get("best_bets", [])

    if not bets:
        print("No edges found above threshold.")
        send_message(f"{emoji} <b>C&amp;P Edge Report — {sport.upper()}</b>\n\nNo edges above threshold right now. Stay patient.")
        return

    # Send header
    send_message(format_header(bets, sport))
    time.sleep(1)

    # Send each edge with game time
    for bet in bets:
        game_key  = bet.get("game", "")
        game_time = game_times.get(game_key, "Time TBD")

        if sport == "wnba":
            msg = format_wnba_alert(bet, game_time)
        elif sport == "nba":
            msg = format_nba_alert(bet, game_time)
        else:
            msg = format_football_alert(bet, sport, game_time)

        send_message(msg)
        time.sleep(1)

    print(f"Sent {len(bets)} alerts to {TELEGRAM_CHANNEL}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="ncaaf", help="Sport: ncaaf, nfl, wnba, nba")
    parser.add_argument("--sims",  type=int, default=10000)
    args = parser.parse_args()
    run_alerts(sport=args.sport, simulations=args.sims)
