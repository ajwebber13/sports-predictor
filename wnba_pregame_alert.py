"""
wnba_pregame_alert.py — Culture & Pulse Analytics
==================================================
Fires a pre-game alert for any WNBA game tipping off in ~2 hours.
Runs every hour via Render cron. Silently exits if no games are in window.

Alert includes:
  - Matchup + tip time
  - Model pick + win probability
  - Final injury report
  - Streak + rest days
  - Edge pick if applicable

Usage:
  python wnba_pregame_alert.py            # live send
  python wnba_pregame_alert.py --dry-run  # print only
"""

import os
import sys
import requests
import argparse
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"
API_BASE         = "https://sports-predictor-api-44a0.onrender.com"
CENTRAL_OFFSET   = -5  # CDT

ESPN_WNBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

# Window: fire alert if tip is between 1.5 and 2.5 hours from now
WINDOW_MIN_HOURS = 1.5
WINDOW_MAX_HOURS = 2.5


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def get_now_ct():
    return datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)


def format_game_time(utc_str: str) -> str:
    try:
        utc_dt     = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        return central_dt.strftime("%I:%M %p CT").lstrip("0")
    except:
        return "TBD"


def hours_until_tip(utc_str: str) -> float:
    try:
        tip_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        delta   = (tip_utc - now_utc).total_seconds() / 3600
        return round(delta, 2)
    except:
        return 99.0


# ─────────────────────────────────────────────────────────────
# FETCH TODAY'S GAMES
# ─────────────────────────────────────────────────────────────

def fetch_today_games() -> list:
    today = (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date().strftime("%Y%m%d")
    url   = f"{ESPN_WNBA_SCOREBOARD}?dates={today}"

    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"ESPN scoreboard error: {e}")
        return []

    games = []
    for event in data.get("events", []):
        comps = event.get("competitions", [])
        if not comps:
            continue

        comp        = comps[0]
        competitors = comp.get("competitors", [])
        home        = next((c for c in competitors if c.get("homeAway") == "home"), {})
        away        = next((c for c in competitors if c.get("homeAway") == "away"), {})

        home_name = home.get("team", {}).get("displayName", "")
        away_name = away.get("team", {}).get("displayName", "")
        utc_time  = event.get("date", "")
        status    = event.get("status", {}).get("type", {}).get("name", "")

        # Only upcoming games
        if status in ("STATUS_FINAL", "STATUS_HALFTIME", "STATUS_IN_PROGRESS"):
            continue

        home_record = home.get("records", [{}])[0].get("summary", "") if home.get("records") else ""
        away_record = away.get("records", [{}])[0].get("summary", "") if away.get("records") else ""

        # Injuries
        home_injuries = _parse_injuries(home)
        away_injuries = _parse_injuries(away)

        games.append({
            "home_team":     home_name,
            "away_team":     away_name,
            "home_record":   home_record,
            "away_record":   away_record,
            "utc_time":      utc_time,
            "game_time":     format_game_time(utc_time),
            "hours_until":   hours_until_tip(utc_time),
            "home_injuries": home_injuries,
            "away_injuries": away_injuries,
            "home_team_id":  home.get("team", {}).get("id", ""),
            "away_team_id":  away.get("team", {}).get("id", ""),
        })

    return games


def _parse_injuries(competitor: dict) -> list:
    injuries = []
    for player in competitor.get("injuries", []):
        name   = player.get("athlete", {}).get("displayName", "")
        status = player.get("status", "")
        if name and status in ["Out", "Doubtful", "Day-To-Day"]:
            injuries.append(f"{name} ({status})")
    return injuries


# ─────────────────────────────────────────────────────────────
# FETCH MODEL PREDICTION FOR ONE GAME
# ─────────────────────────────────────────────────────────────

def fetch_prediction(home: str, away: str) -> dict:
    try:
        r    = requests.get(f"{API_BASE}/wnba/predictions", params={"simulations": 5000}, timeout=60)
        data = r.json()
    except Exception as e:
        print(f"Model API error: {e}")
        return {}

    key = f"{away} @ {home}"
    for bet in data.get("best_bets", []):
        if bet.get("game") == key:
            game       = bet.get("game", "")
            model_prob = bet.get("model_prob", 50)
            edge       = round(bet.get("edge", 0) * 100, 1)
            bet_label  = bet.get("bet", "")

            parts       = game.split(" @ ")
            home_team   = parts[1] if len(parts) == 2 else ""
            away_team   = parts[0] if len(parts) == 2 else ""
            bet_on_home = home_team.lower() in bet_label.lower()
            home_prob   = model_prob if bet_on_home else round(100 - model_prob, 1)
            away_prob   = round(100 - model_prob, 1) if bet_on_home else model_prob

            return {
                "home_prob":        home_prob,
                "away_prob":        away_prob,
                "predicted_winner": home_team if home_prob > away_prob else away_team,
                "winner_prob":      max(home_prob, away_prob),
                "edge":             edge,
                "has_edge":         edge >= 10,
                "pick_label":       bet_label if edge >= 10 else "",
            }

    return {}


# ─────────────────────────────────────────────────────────────
# FETCH STREAK
# ─────────────────────────────────────────────────────────────

def fetch_streak(team_id: str) -> dict:
    if not team_id:
        return {}
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/{team_id}/schedule"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except:
        return {}

    today    = (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()
    past     = []

    for event in data.get("events", []):
        utc_str   = event.get("date", "")
        completed = event.get("competitions", [{}])[0].get("status", {}).get("type", {}).get("completed", False)
        if not completed or not utc_str:
            continue
        try:
            utc_dt   = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
            game_day = (utc_dt + timedelta(hours=CENTRAL_OFFSET)).date()
        except:
            continue
        if game_day >= today:
            continue

        comp      = event.get("competitions", [{}])[0]
        team_comp = next((c for c in comp.get("competitors", []) if c.get("team", {}).get("id") == team_id), None)
        if not team_comp:
            continue
        past.append({"date": game_day, "result": "W" if team_comp.get("winner") else "L"})

    if not past:
        return {}

    past.sort(key=lambda x: x["date"], reverse=True)
    rest_days    = (today - past[0]["date"]).days
    streak_type  = past[0]["result"]
    streak_count = sum(1 for g in past if g["result"] == streak_type and past.index(g) == past[:past.index(g)+1].count(g) - 1)

    # Simple streak count
    count = 0
    for g in past:
        if g["result"] == streak_type:
            count += 1
        else:
            break

    return {"type": streak_type, "count": count, "rest_days": rest_days}


# ─────────────────────────────────────────────────────────────
# FORMAT ALERT
# ─────────────────────────────────────────────────────────────

def format_pregame_alert(game: dict, pred: dict, home_streak: dict, away_streak: dict) -> str:
    home = game["home_team"]
    away = game["away_team"]
    lines = []

    lines.append(f"🏀 <b>C&amp;P Picks — WNBA Pregame Alert</b>")
    lines.append(f"⏰ Tip-off in ~2 hours")
    lines.append("")
    lines.append(f"🏟 <b>{away} @ {home}</b>")
    lines.append(f"🕐 {game['game_time']}")
    lines.append("───────────────────")

    # Records
    rec = []
    if game["away_record"]: rec.append(f"{away}: {game['away_record']}")
    if game["home_record"]: rec.append(f"{home}: {game['home_record']}")
    if rec: lines.append("📋 " + " | ".join(rec))

    # Streaks + rest
    sp = []
    for team, streak in [(away, away_streak), (home, home_streak)]:
        if streak:
            p = team
            if streak.get("type") and streak.get("count"):
                p += f" ({streak['type']}{streak['count']})"
            if streak.get("rest_days") is not None:
                rest = streak["rest_days"]
                p += f" · {'B2B' if rest == 0 else '1 day rest' if rest == 1 else f'{rest} days rest'}"
            sp.append(p)
    if sp: lines.append("🔥 " + " | ".join(sp))

    # Injuries
    if game["away_injuries"]: lines.append(f"🚑 {away}: {', '.join(game['away_injuries'])}")
    if game["home_injuries"]: lines.append(f"🚑 {home}: {', '.join(game['home_injuries'])}")

    # Prediction
    lines.append("───────────────────")
    if pred:
        lines.append(f"📊 Model: {away} {pred['away_prob']}% | {home} {pred['home_prob']}%")
        lines.append(f"🤖 <b>Model Pick: {pred['predicted_winner']} ({pred['winner_prob']}%)</b>")
        if pred.get("has_edge") and pred.get("pick_label"):
            lines.append(f"✅ <b>EDGE PICK: {pred['pick_label']} | +{pred['edge']}%</b>")
        else:
            lines.append("⚠️ No edge pick (below threshold)")
    else:
        lines.append("📊 Model prediction unavailable")

    lines.append("")
    lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# SEND
# ─────────────────────────────────────────────────────────────

def send_message(text: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  TELEGRAM_CHANNEL,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("Alert sent.")
    else:
        print(f"Telegram error: {r.status_code} {r.text}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run(dry_run: bool = False):
    print(f"Checking for games tipping in {WINDOW_MIN_HOURS}–{WINDOW_MAX_HOURS} hours...")

    games = fetch_today_games()
    if not games:
        print("No games today.")
        return

    alerts_fired = 0

    for game in games:
        hrs = game["hours_until"]
        if not (WINDOW_MIN_HOURS <= hrs <= WINDOW_MAX_HOURS):
            print(f"  {game['away_team']} @ {game['home_team']} — {hrs:.1f} hrs away, skipping")
            continue

        print(f"  {game['away_team']} @ {game['home_team']} — {hrs:.1f} hrs — FIRING ALERT")

        pred         = fetch_prediction(game["home_team"], game["away_team"])
        home_streak  = fetch_streak(game["home_team_id"])
        away_streak  = fetch_streak(game["away_team_id"])
        alert        = format_pregame_alert(game, pred, home_streak, away_streak)

        if dry_run:
            print("\n--- DRY RUN ---")
            print(alert)
            print()
        else:
            send_message(alert)

        alerts_fired += 1

    if alerts_fired == 0:
        print("No games in pregame window. Exiting silently.")
    else:
        print(f"Done. {alerts_fired} alert(s) fired.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
