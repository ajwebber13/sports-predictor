"""
telegram_alerts.py
===================
Sends game prediction alerts to Culture & Pulse Picks Telegram channel.
Sports: NFL, CFB, WNBA, NBA, College Basketball

Season gates prevent alerts during inactive periods.
Date filtering ensures only today's games (Central Time) are sent.
Game times pulled from ESPN (free, no API key needed).
Alert throttle caps picks per slate and removes correlated bets.
"""

import requests
import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta

try:
    from database import log_prediction
    LOGGING_ENABLED = True
except ImportError:
    LOGGING_ENABLED = False

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"
API_BASE         = "https://sports-predictor-api-44a0.onrender.com"
CENTRAL_OFFSET   = -5  # CDT


# ─────────────────────────────────────────────────────────────
# ESPN SCHEDULE ENDPOINTS
# ─────────────────────────────────────────────────────────────

ESPN_SCHEDULE_ENDPOINTS = {
    "nfl":   "football/nfl",
    "ncaaf": "football/college-football",
    "nba":   "basketball/nba",
    "ncaab": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
    "wnba":  "basketball/wnba",
}


# ─────────────────────────────────────────────────────────────
# SEASON GATES
# ─────────────────────────────────────────────────────────────

SEASON_WINDOWS = {
    "nfl":   (9, 2),
    "ncaaf": (8, 1),
    "ncaab": (11, 4),
    "ncaaw": (11, 4),
    "wnba":  (5, 10),
    "nba":   (10, 5),
}

def is_in_season(sport: str) -> bool:
    window = SEASON_WINDOWS.get(sport)
    if not window:
        return True
    start_month, end_month = window
    current_month = datetime.now().month
    if start_month <= end_month:
        return start_month <= current_month <= end_month
    else:
        return current_month >= start_month or current_month <= end_month


# ─────────────────────────────────────────────────────────────
# DATE HELPERS
# ─────────────────────────────────────────────────────────────

def get_today_ct() -> datetime.date:
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def is_today_ct(utc_str: str) -> bool:
    try:
        utc_dt     = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        return central_dt.date() == get_today_ct()
    except:
        return True


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def format_game_time(utc_str: str) -> str:
    try:
        utc_dt     = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        day        = central_dt.strftime("%a %b ")
        day       += str(central_dt.day)
        t          = central_dt.strftime(" · %I:%M %p CT")
        return day + t
    except:
        return "Time TBD"


def get_game_times(sport: str) -> tuple:
    endpoint = ESPN_SCHEDULE_ENDPOINTS.get(sport)
    if not endpoint:
        return {}, {}

    url = f"http://site.api.espn.com/apis/site/v2/sports/{endpoint}/scoreboard"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ESPN game times error ({sport}): {e}")
        return {}, {}

    times     = {}
    times_raw = {}

    for event in data.get("events", []):
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp        = competitions[0]
        competitors = comp.get("competitors", [])
        home_team   = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), "")
        away_team   = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), "")
        utc_time    = event.get("date", "")
        fmt         = format_game_time(utc_time) if utc_time else "Time TBD"

        for key in [f"{away_team} @ {home_team}", f"{home_team} @ {away_team}", home_team, away_team]:
            times[key]     = fmt
            times_raw[key] = utc_time

    print(f"ESPN returned {len(data.get('events', []))} events for {sport}")
    return times, times_raw


def send_message(text: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHANNEL, "text": text, "parse_mode": "HTML"}
    r       = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("Sent successfully")
    else:
        print(f"Failed: {r.status_code} {r.text}")


def sport_emoji(sport: str) -> str:
    return "🏈" if sport in ["ncaaf", "nfl"] else "🏀"


def sport_label(sport: str) -> str:
    labels = {
        "ncaaf": "College Football",
        "nfl":   "NFL",
        "ncaab": "College Basketball (Men)",
        "ncaaw": "College Basketball (Women)",
        "wnba":  "WNBA",
        "nba":   "NBA",
    }
    return labels.get(sport, sport.upper())


def edge_label(edge_pct: float) -> str:
    if edge_pct >= 10: return "★★★ STRONG EDGE"
    if edge_pct >= 6:  return "★★  MODERATE EDGE"
    return "★   SLIGHT EDGE"


def get_recommended_prob(bet: dict) -> float:
    """
    Returns the model's confidence in the PICKED team winning.
    model_prob is always the HOME team win probability.
    If we're betting the away team, confidence = 100 - model_prob.
    """
    model_prob = bet.get("model_prob", 50)
    game       = bet.get("game", "")
    bet_label  = bet.get("bet", "")
    parts      = game.split(" @ ")
    home_team  = parts[1] if len(parts) == 2 else ""
    if home_team.lower() in bet_label.lower():
        return round(float(model_prob), 1)
    else:
        return round(100 - float(model_prob), 1)


def fmt_odds(odds) -> str:
    if odds is None:
        return ""
    try:
        odds = int(odds)
        return f"+{odds}" if odds > 0 else str(odds)
    except:
        return ""


def get_raw_time_for_bet(bet: dict, times_raw: dict) -> str:
    game  = bet.get("game", "")
    parts = game.split(" @ ")
    for key in [game] + parts:
        raw = times_raw.get(key)
        if raw:
            return raw
    return ""


# ─────────────────────────────────────────────────────────────
# FORMATTERS
# ─────────────────────────────────────────────────────────────

def format_header(bets: list, sport: str) -> str:
    emoji    = sport_emoji(sport)
    label    = sport_label(sport)
    top_edge = max((b.get("edge", 0) * 100 for b in bets), default=0)
    today    = get_today_ct().strftime("%B %d, %Y")
    return (
        f"{emoji} <b>Culture &amp; Pulse Picks</b>\n"
        f"📅 {today} — {label}\n"
        f"<b>Edges found:</b> {len(bets)}  |  <b>Top edge:</b> +{round(top_edge, 1)}%\n\n"
        f"Full slate below 👇"
    )


def format_slate_summary(bets: list, sport: str, suppressed: list = None) -> str:
    emoji = sport_emoji(sport)
    label = sport_label(sport)
    today = get_today_ct().strftime("%B %d, %Y")

    lines = [
        f"{emoji} <b>Culture &amp; Pulse Picks</b>",
        f"📅 {today} — {label} Slate\n",
    ]

    if bets:
        for b in sorted(bets, key=lambda x: x.get("edge", 0), reverse=True):
            game      = b.get("game", "")
            bet_label = b.get("bet", "")
            edge_pct  = round(b.get("edge", 0) * 100, 1)
            stars     = "★★★" if edge_pct >= 15 else "★★" if edge_pct >= 8 else "★"
            lines.append(f"✅ {game}")
            lines.append(f"   {bet_label} | Edge +{edge_pct}% {stars}\n")
    else:
        lines.append("No qualifying edges found today.\n")

    if suppressed:
        try:
            from alert_throttle import format_throttle_summary
            lines.append(format_throttle_summary(bets, suppressed, sport))
        except Exception:
            lines.append(f"<i>{len(suppressed)} pick(s) filtered by throttle</i>")

    lines.append("\nFull breakdown for each pick coming up 👇")
    return "\n".join(lines)


def format_alert(bet: dict, sport: str, game_time: str) -> str:
    emoji      = sport_emoji(sport)
    label      = sport_label(sport)
    game       = bet.get("game", "")
    bet_label  = bet.get("bet", "")
    odds       = bet.get("odds")
    edge_pct   = round(bet.get("edge", 0) * 100, 1)
    model_prob = bet.get("model_prob", 0)
    implied    = bet.get("implied_prob", 0)
    projected  = bet.get("projected")

    home_record   = bet.get("home_record", "")
    away_record   = bet.get("away_record", "")
    home_rest     = bet.get("home_rest")
    away_rest     = bet.get("away_rest")
    home_injuries = bet.get("home_injuries", "")
    away_injuries = bet.get("away_injuries", "")

    parts       = game.split(" @ ")
    away_team   = parts[0] if len(parts) == 2 else ""
    home_team   = parts[1] if len(parts) == 2 else ""
    home_prob = round(float(model_prob), 1)
    away_prob = round(100 - home_prob, 1)

    odds_str  = f" ({fmt_odds(odds)})" if odds else ""
    proj_line = f"\n📊 <b>Projected:</b> {projected}" if projected else ""

    rec_parts = []
    if away_record:
        rec_parts.append(f"{away_team}: {away_record}")
    if home_record:
        rec_parts.append(f"{home_team}: {home_record}")
    records_line = "\n📋 <b>Records:</b> " + " | ".join(rec_parts) if rec_parts else ""

    rest_parts = []
    if away_rest is not None:
        rest_parts.append(f"{away_team}: {away_rest}d rest")
    if home_rest is not None:
        rest_parts.append(f"{home_team}: {home_rest}d rest")
    rest_line = "\n💤 <b>Rest:</b> " + " | ".join(rest_parts) if rest_parts else ""

    inj_lines = ""
    if home_injuries:
        inj_lines += f"\n🚑 <b>{home_team} Out/Doubtful:</b> {home_injuries}"
    if away_injuries:
        inj_lines += f"\n🚑 <b>{away_team} Out/Doubtful:</b> {away_injuries}"

    try:
        from clv_tracker import log_pick
        bet_team = bet_label.replace(" ML", "").strip()
        log_pick(
            sport      = sport,
            home_team  = home_team,
            away_team  = away_team,
            bet_team   = bet_team,
            model_prob = model_prob,
            edge       = edge_pct,
        )
    except Exception:
        pass

    return (
        f"{emoji} <b>{label} — PICK ALERT</b>\n\n"
        f"<b>{game}</b>\n"
        f"🕐 {game_time}\n\n"
        f"✅ <b>Pick:</b> {bet_label}{odds_str}\n"
        f"📈 <b>Edge:</b> +{edge_pct}% — {edge_label(edge_pct)}\n"
        f"{proj_line}\n\n"
        f"<b>WIN PROBABILITY</b>\n"
        f"{away_team}: {away_prob}%\n"
        f"{home_team}: {home_prob}%\n"
        f"Market: {implied}%\n"
        f"{records_line}"
        f"{rest_line}"
        f"{inj_lines}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Culture & Pulse Analytics</i>\n"
        f"<i>For entertainment only. Bet responsibly.</i>"
    )


def format_no_games(sport: str) -> str:
    emoji = sport_emoji(sport)
    label = sport_label(sport)
    today = get_today_ct().strftime("%B %d, %Y")
    return (
        f"{emoji} <b>Culture &amp; Pulse Picks — {label}</b>\n\n"
        f"📅 {today}\n"
        f"No {label} games scheduled today."
    )


# ─────────────────────────────────────────────────────────────
# API ROUTING
# ─────────────────────────────────────────────────────────────

def get_edges_url(sport: str, simulations: int) -> str:
    endpoints = {
        "nfl":   f"{API_BASE}/nfl/edges",
        "ncaaf": f"{API_BASE}/ncaaf/edges",
        "ncaab": f"{API_BASE}/ncaab/edges",
        "ncaaw": f"{API_BASE}/ncaaw/edges",
        "wnba":  f"{API_BASE}/wnba/edges",
        "nba":   f"{API_BASE}/nba/edges",
    }
    url = endpoints.get(sport)
    if not url:
        raise ValueError(f"Unknown sport: {sport}")
    return url


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run_alerts(sport: str = "ncaaf", simulations: int = 10000):
    emoji       = sport_emoji(sport)
    label       = sport_label(sport)
    today_label = get_today_ct().strftime("%B %d, %Y")

    if not is_in_season(sport):
        print(f"{label} is not in season. Skipping.")
        return

    # ── SLATE DIGEST (WNBA only) — fires before edge alerts ──
    if sport == "wnba":
        try:
            from wnba_slate_digest import run_digest
            print("Running WNBA slate digest...")
            run_digest(dry_run=False)
            time.sleep(2)
        except Exception as e:
            print(f"Slate digest error (non-fatal): {e}")

    print(f"Fetching edges for {sport}...")
    game_times, game_times_raw = get_game_times(sport)
    print(f"Game times loaded: {len(game_times)} entries")

    try:
        url  = get_edges_url(sport, simulations)
        r    = requests.get(url, params={"simulations": simulations}, timeout=60)
        data = r.json()
    except Exception as e:
        print(f"Could not reach API: {e}")
        return

    bets_raw = data.get("best_bets", [])

    # ── DATE FILTER ──
    bets = []
    for bet in bets_raw:
        raw_time = get_raw_time_for_bet(bet, game_times_raw)
        if raw_time and not is_today_ct(raw_time):
            print(f"Skipping stale game (not today): {bet.get('game')} — {raw_time}")
            continue
        bets.append(bet)

    if not bets:
        print(f"No {label} games today ({today_label}).")
        # WNBA slate digest (above) already sends its own "no games" message —
        # skip the duplicate here.
        if sport != "wnba":
            send_message(format_no_games(sport))
        return

    if LOGGING_ENABLED:
        for bet in bets:
            try:
                log_prediction(bet, sport)
            except Exception as e:
                print(f"DB prediction save failed: {e}")

    # ── THROTTLE: edge filter + correlation filter + slate cap ──
    try:
        from alert_throttle import throttle_bets
        clean_bets, suppressed, throttle_log = throttle_bets(bets, sport)
        print(throttle_log)
    except Exception as e:
        print(f"Throttle error — falling back to confidence filter: {e}")
        # Fallback to basic confidence filter if throttle fails
        clean_bets = []
        suppressed = []
        for bet in bets:
            if get_recommended_prob(bet) >= 57:
                clean_bets.append(bet)
            else:
                suppressed.append(bet)

    # ── WNBA: digest already sent edge picks inline — skip duplicate summary/alerts ──
    if sport == "wnba":
        if clean_bets:
            print(f"WNBA: {len(clean_bets)} edge(s) already included in slate digest. No duplicate alerts sent.")
        else:
            print("WNBA: No clean edges — slate digest already handled game-level output. No summary sent.")
        return

    if not clean_bets:
        print("All alerts filtered. Nothing sent.")
        send_message(
            f"{emoji} <b>C&amp;P Picks — {label}</b>\n\n"
            f"📅 {today_label}\n"
            f"No clean edges after model validation. Stay patient."
        )
        return

    # ── SEND SLATE SUMMARY ──
    send_message(format_slate_summary(clean_bets, sport, suppressed=suppressed))
    time.sleep(1)

    # ── SEND INDIVIDUAL ALERTS ──
    for bet in clean_bets:
        game      = bet.get("game", "")
        game_time = game_times.get(game, "Time TBD")

        if game_time == "Time TBD":
            parts = game.split(" @ ")
            if len(parts) == 2:
                game_time = game_times.get(parts[0], game_times.get(parts[1], "Time TBD"))

        msg = format_alert(bet, sport, game_time)
        send_message(msg)
        time.sleep(1)

    print(f"Sent {len(clean_bets)} alerts for {label} on {today_label} to {TELEGRAM_CHANNEL}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="ncaaf")
    parser.add_argument("--sims", type=int, default=10000)
    args = parser.parse_args()
    run_alerts(sport=args.sport, simulations=args.sims)
