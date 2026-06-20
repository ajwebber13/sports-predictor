"""
wnba_slate_digest.py — Culture & Pulse Analytics
=================================================
Sends a full WNBA daily slate digest to Telegram BEFORE edge alerts fire.
Shows every game with:
  - Model's predicted winner + win probability
  - Team records
  - Rest days
  - Current streak (W/L + length)
  - Key injuries (from ESPN)
  - Star player streaks (20+ pts, double-doubles, etc.)
  - Edge pick flag or "no pick" label

Data sources:
  - ESPN free API (schedule, scores, injuries, box scores) — no credits used
  - Your existing prediction engine via API

Usage:
  python wnba_slate_digest.py              # send today's digest
  python wnba_slate_digest.py --dry-run    # print without sending
"""

import os
import sys
import requests
import argparse
import time
from datetime import datetime, timezone, timedelta

try:
    from wnba_news_feed import fetch_all_headlines, get_game_news, get_general_news
    NEWS_ENABLED = True
except ImportError:
    NEWS_ENABLED = False

try:
    from intel_feed import fetch_injuries
    INJURIES_ENABLED = True
except ImportError:
    INJURIES_ENABLED = False

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"
API_BASE         = "https://sports-predictor-api-44a0.onrender.com"
CENTRAL_OFFSET   = -5  # CDT

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

ESPN_WNBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
ESPN_WNBA_SUMMARY    = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"
ESPN_WNBA_TEAMS      = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams"


# ─────────────────────────────────────────────────────────────
# STAR PLAYERS PER TEAM
# Update as rosters change each season
# ─────────────────────────────────────────────────────────────

WNBA_STAR_PLAYERS = {
    "Las Vegas Aces":          ["A'ja Wilson", "Kelsey Plum", "Jackie Young"],
    "New York Liberty":        ["Breanna Stewart", "Sabrina Ionescu", "Jonquel Jones"],
    "Seattle Storm":           ["Nneka Ogwumike", "Skylar Diggins-Smith", "Jewell Loyd"],
    "Minnesota Lynx":          ["Napheesa Collier", "Courtney Williams", "Kayla McBride"],
    "Connecticut Sun":         ["Alyssa Thomas", "DeWanna Bonner", "Brionna Jones"],
    "Indiana Fever":           ["Caitlin Clark", "Aliyah Boston", "NaLyssa Smith"],
    "Chicago Sky":             ["Angel Reese", "Marina Mabrey", "Chennedy Carter"],
    "Atlanta Dream":           ["Rhyne Howard", "Allisha Gray", "Cheyenne Parker"],
    "Phoenix Mercury":         ["Diana Taurasi", "Brittney Griner", "Sophie Cunningham"],
    "Los Angeles Sparks":      ["Dearica Hamby", "Rickea Jackson", "Li Yueru"],
    "Washington Mystics":      ["Elena Delle Donne", "Shakira Austin", "Stefanie Dolson"],
    "Dallas Wings":            ["Arike Ogunbowale", "Satou Sabally", "Natasha Howard"],
    "Golden State Valkyries":  ["Kayla Thornton", "Kate Martin", "Tiffany Hayes"],
    "Toronto Tempo":           ["Natalie Achonwa", "Stephanie Mavunga"],
    "Portland Fire":           ["Kelsey Mitchell", "Lexie Hull"],
}

# Thresholds for flagging a streak as notable
STAR_PTS_THRESHOLD  = 20   # pts in last N games
STAR_STREAK_GAMES   = 3    # minimum games to call it a streak
DOUBLE_DOUBLE_GAMES = 3    # games needed for double-double streak


# ─────────────────────────────────────────────────────────────
# DATE HELPERS
# ─────────────────────────────────────────────────────────────

def get_today_ct() -> datetime.date:
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def format_game_time(utc_str: str) -> str:
    try:
        utc_dt     = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        return central_dt.strftime("%I:%M %p CT").lstrip("0")
    except:
        return "TBD"


# ─────────────────────────────────────────────────────────────
# ESPN GAME FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_today_games() -> list:
    """
    Pull today's WNBA games from ESPN scoreboard.
    Returns list of game dicts with teams, time, status, and ESPN event ID.
    """
    today = get_today_ct().strftime("%Y%m%d")
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

        # Records
        home_record = home.get("records", [{}])[0].get("summary", "") if home.get("records") else ""
        away_record = away.get("records", [{}])[0].get("summary", "") if away.get("records") else ""

        # Game time
        utc_time  = event.get("date", "")
        game_time = format_game_time(utc_time)

        # Status
        status    = event.get("status", {}).get("type", {}).get("name", "")
        completed = event.get("status", {}).get("type", {}).get("completed", False)

        # Injuries from competitors
        home_injuries = _parse_injuries(home)
        away_injuries = _parse_injuries(away)

        games.append({
            "event_id":      event.get("id", ""),
            "home_team":     home_name,
            "away_team":     away_name,
            "home_record":   home_record,
            "away_record":   away_record,
            "home_team_id":  home.get("team", {}).get("id", ""),
            "away_team_id":  away.get("team", {}).get("id", ""),
            "game_time":     game_time,
            "utc_time":      utc_time,
            "status":        status,
            "completed":     completed,
            "home_injuries": home_injuries,
            "away_injuries": away_injuries,
        })

    return games


def _parse_injuries(competitor: dict) -> list:
    """Pull injury data from ESPN competitor block if available."""
    injuries = []
    for player in competitor.get("injuries", []):
        name   = player.get("athlete", {}).get("displayName", "")
        status = player.get("status", "")
        if name and status in ["Out", "Doubtful", "Questionable"]:
            injuries.append(f"{name} ({status})")
    return injuries


# ─────────────────────────────────────────────────────────────
# STREAK FETCHER — pulls last 10 game results per team
# ─────────────────────────────────────────────────────────────

def fetch_team_streak(team_id: str) -> dict:
    """
    Pull last 10 games for a team from ESPN.
    Returns streak dict: {"type": "W"/"L", "count": int, "rest_days": int}
    """
    if not team_id:
        return {"type": "", "count": 0, "rest_days": None}

    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/{team_id}/schedule"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  Streak fetch error (team {team_id}): {e}")
        return {"type": "", "count": 0, "rest_days": None}

    today    = get_today_ct()
    events   = data.get("events", [])
    past     = []

    for event in events:
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

        # Determine W/L for this team
        comp        = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        team_comp   = next((c for c in competitors if c.get("team", {}).get("id") == team_id), None)
        if not team_comp:
            continue

        winner = team_comp.get("winner", False)
        past.append({"date": game_day, "result": "W" if winner else "L"})

    if not past:
        return {"type": "", "count": 0, "rest_days": None}

    # Sort by date descending
    past.sort(key=lambda x: x["date"], reverse=True)

    # Calculate rest days
    last_game_date = past[0]["date"]
    rest_days      = (today - last_game_date).days

    # Calculate current streak
    streak_type  = past[0]["result"]
    streak_count = 0
    for game in past:
        if game["result"] == streak_type:
            streak_count += 1
        else:
            break

    return {
        "type":      streak_type,
        "count":     streak_count,
        "rest_days": rest_days,
    }


# ─────────────────────────────────────────────────────────────
# STAR PLAYER STREAK FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_star_player_streaks(team_name: str) -> list:
    """
    Pull recent box scores for a team's star players.
    Returns list of notable streak strings.
    """
    stars   = WNBA_STAR_PLAYERS.get(team_name, [])
    notices = []

    if not stars:
        return notices

    # Get last 7 days of completed game IDs
    today   = get_today_ct()
    game_ids = []
    for days_back in range(1, 15):
        check_date = (today - timedelta(days=days_back)).strftime("%Y%m%d")
        url        = f"{ESPN_WNBA_SCOREBOARD}?dates={check_date}"
        try:
            r    = requests.get(url, headers=HEADERS, timeout=8)
            data = r.json()
            for event in data.get("events", []):
                completed = event.get("status", {}).get("type", {}).get("completed", False)
                # Check if this team played
                comps       = event.get("competitions", [{}])
                competitors = comps[0].get("competitors", []) if comps else []
                team_names  = [c.get("team", {}).get("displayName", "") for c in competitors]
                if completed and team_name in team_names:
                    game_ids.append(event.get("id"))
                    if len(game_ids) >= STAR_STREAK_GAMES:
                        break
        except:
            pass
        if len(game_ids) >= STAR_STREAK_GAMES:
            break

    if not game_ids:
        print(f"  No recent completed games found for {team_name} star players")
        return notices

    # Build per-player game log
    player_logs = {star: [] for star in stars}

    for game_id in game_ids[:STAR_STREAK_GAMES + 2]:  # a few extra for buffer
        url = f"{ESPN_WNBA_SUMMARY}?event={game_id}"
        try:
            r        = requests.get(url, headers=HEADERS, timeout=10)
            data     = r.json()
            boxscore = data.get("boxscore", {})
            teams    = boxscore.get("players", [])

            for team_data in teams:
                t_name = team_data.get("team", {}).get("displayName", "")
                if t_name != team_name:
                    continue

                stats_list = team_data.get("statistics", [])
                if not stats_list:
                    continue

                stat_keys = stats_list[0].get("keys", [])
                athletes  = stats_list[0].get("athletes", [])

                for ath in athletes:
                    p_name = ath.get("athlete", {}).get("displayName", "")
                    if p_name not in player_logs:
                        continue

                    raw = ath.get("stats", [])
                    if not raw:
                        continue

                    def gs(key):
                        try:
                            idx = stat_keys.index(key)
                            val = raw[idx]
                            # ESPN sometimes returns "N/A" or dash for DNP
                            return float(val) if val not in ("N/A", "-", "", None) else 0.0
                        except:
                            return 0.0

                    pts = gs("points")
                    reb = gs("rebounds")
                    ast = gs("assists")

                    player_logs[p_name].append({
                        "pts": pts,
                        "reb": reb,
                        "ast": ast,
                    })
        except Exception as e:
            print(f"  Box score error ({game_id}): {e}")
            continue

    # Evaluate streaks
    for player, games in player_logs.items():
        if len(games) < STAR_STREAK_GAMES:
            continue

        recent = games[:STAR_STREAK_GAMES]

        # Points streak
        pts_above = [g for g in recent if g["pts"] >= STAR_PTS_THRESHOLD]
        if len(pts_above) >= STAR_STREAK_GAMES:
            avg_pts = round(sum(g["pts"] for g in recent) / len(recent), 1)
            notices.append(f"⚡ {player}: {avg_pts} PPG last {STAR_STREAK_GAMES}G")

        # Double-double streak
        dd_games = [g for g in recent if g["pts"] >= 10 and (g["reb"] >= 10 or g["ast"] >= 10)]
        if len(dd_games) >= DOUBLE_DOUBLE_GAMES:
            notices.append(f"⚡ {player}: Double-double last {len(dd_games)}G")

    return notices


# ─────────────────────────────────────────────────────────────
# MODEL PREDICTIONS FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_model_predictions() -> dict:
    """
    Pull all WNBA predictions from your FastAPI backend.
    Returns dict keyed by "AWAY @ HOME" game string.
    """
    try:
        r    = requests.get(f"{API_BASE}/wnba/edges", params={"simulations": 5000}, timeout=60)
        data = r.json()
    except Exception as e:
        print(f"Model API error: {e}")
        return {}

    predictions = {}
    for bet in data.get("best_bets", []):
        game       = bet.get("game", "")
        model_prob = bet.get("model_prob", 50)
        edge       = round(bet.get("edge", 0) * 100, 1)
        bet_label  = bet.get("bet", "")
        odds       = bet.get("odds")
        implied    = bet.get("implied_prob", 50)

        parts     = game.split(" @ ")
        home_team = parts[1] if len(parts) == 2 else ""
        away_team = parts[0] if len(parts) == 2 else ""

        bet_on_home = home_team.lower() in bet_label.lower()
        home_prob   = model_prob if bet_on_home else round(100 - model_prob, 1)
        away_prob   = round(100 - model_prob, 1) if bet_on_home else model_prob

        predicted_winner = home_team if home_prob > away_prob else away_team
        winner_prob      = max(home_prob, away_prob)

        has_edge    = edge >= 10
        pick_label  = bet_label if has_edge else ""

        predictions[game] = {
            "home_team":       home_team,
            "away_team":       away_team,
            "home_prob":       home_prob,
            "away_prob":       away_prob,
            "predicted_winner": predicted_winner,
            "winner_prob":     winner_prob,
            "edge":            edge,
            "has_edge":        has_edge,
            "pick_label":      pick_label,
            "odds":            odds,
            "implied_prob":    implied,
        }

    return predictions


# ─────────────────────────────────────────────────────────────
# MATCH ESPN GAME TO MODEL PREDICTION
# ─────────────────────────────────────────────────────────────

def match_prediction(game: dict, predictions: dict) -> dict:
    """
    Try to match ESPN game to a model prediction.
    Model uses "AWAY @ HOME" format.
    """
    home = game["home_team"]
    away = game["away_team"]

    # Try exact match first
    key = f"{away} @ {home}"
    if key in predictions:
        return predictions[key]

    # Try fuzzy match on team name keywords
    for pred_key, pred in predictions.items():
        if pred["home_team"] in home or home in pred["home_team"]:
            if pred["away_team"] in away or away in pred["away_team"]:
                return pred

    return {}


# ─────────────────────────────────────────────────────────────
# FORMAT DIGEST
# ─────────────────────────────────────────────────────────────

def format_streak(streak: dict) -> str:
    if not streak.get("type") or not streak.get("count"):
        return ""
    return f"{streak['type']}{streak['count']}"


def format_rest(rest_days) -> str:
    if rest_days is None:
        return ""
    if rest_days == 1:
        return "1 day rest"
    if rest_days == 0:
        return "B2B"
    return f"{rest_days} days rest"


def format_digest(games: list, predictions: dict, streaks: dict, star_notices: dict, all_news: list = None, injury_map: dict = None) -> list:
    """Returns a list of messages — header + one per game."""
    today       = get_today_ct().strftime("%B %d, %Y")
    all_news    = all_news or []
    injury_map  = injury_map or {}
    used_titles = set()
    messages    = []

    # ── MESSAGE 1: HEADER + AROUND THE W ──
    header = [
        "🏀 <b>C&amp;P Picks — WNBA Morning Briefing</b>",
        f"📅 {today}",
        f"<b>{len(games)} game(s) today</b>",
        "",
    ]
    if NEWS_ENABLED and all_news:
        general = get_general_news(all_news, used_titles)
        if general:
            header.append("📡 <b>Around the W</b>")
            for h in general:
                header.append(h)
                used_titles.add(h)
    messages.append("\n".join(header))

    if not games:
        messages.append("<i>No WNBA games scheduled today.</i>")
        return messages

    # ── ONE MESSAGE PER GAME ──
    for g in games:
        home = g["home_team"]
        away = g["away_team"]

        pred         = match_prediction(g, predictions)
        home_streak  = streaks.get(home, {})
        away_streak  = streaks.get(away, {})
        home_notices = star_notices.get(home, [])
        away_notices = star_notices.get(away, [])

        lines = [f"🏟 <b>{away} @ {home}</b>", f"🕐 {g['game_time']}"]

        # Records
        rec = []
        if g["away_record"]: rec.append(f"{away}: {g['away_record']}")
        if g["home_record"]:  rec.append(f"{home}: {g['home_record']}")
        if rec: lines.append("📋 " + " | ".join(rec))

        # Streaks + rest
        sp = []
        for team, streak in [(away, away_streak), (home, home_streak)]:
            s = format_streak(streak)
            r = format_rest(streak.get("rest_days"))
            if s or r:
                p = team
                if s: p += f" ({s})"
                if r: p += f" · {r}"
                sp.append(p)
        if sp: lines.append("🔥 " + " | ".join(sp))

        # Injuries
        away_inj = injury_map.get(away, g.get("away_injuries", []))
        home_inj = injury_map.get(home, g.get("home_injuries", []))
        if away_inj: lines.append(f"🚑 {away}: {', '.join(away_inj)}")
        if home_inj: lines.append(f"🚑 {home}: {', '.join(home_inj)}")

        # Star notices
        for notice in (away_notices + home_notices)[:3]:
            lines.append(notice)

        # Game news
        if NEWS_ENABLED and all_news:
            for h in get_game_news(home, away, all_news):
                if h not in used_titles:
                    lines.append(h)
                    used_titles.add(h)

        # Prediction
        lines.append("")
        if pred:
            away_prob = pred.get("away_prob", 50)
            home_prob = pred.get("home_prob", 50)
            winner    = pred.get("predicted_winner", "")
            w_prob    = pred.get("winner_prob", 50)
            lines.append(f"📊 {away} {away_prob}% | {home} {home_prob}%")
            lines.append(f"🤖 <b>Model Pick: {winner} ({w_prob}%)</b>")
            if pred.get("has_edge") and pred.get("pick_label"):
                lines.append(f"✅ <b>EDGE PICK: {pred['pick_label']} | +{pred.get('edge', 0)}%</b>")
            else:
                lines.append("⚠️ No edge pick (below threshold)")
        else:
            lines.append("📊 Model prediction unavailable")

        lines.append("")
        lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
        messages.append("\n".join(lines))

    return messages


# ─────────────────────────────────────────────────────────────
# TELEGRAM SENDER
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
        print("Digest sent successfully.")
    else:
        print(f"Telegram error: {r.status_code} {r.text}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run_digest(dry_run: bool = False):
    today = get_today_ct().strftime("%B %d, %Y")
    print(f"Running WNBA slate digest for {today}...")

    # 1. Get today's games
    print("Fetching today's games from ESPN...")
    games = fetch_today_games()
    print(f"  Found {len(games)} game(s)")

    if not games:
        msg = (
            "🏀 <b>C&amp;P Picks — WNBA Daily Slate</b>\n"
            f"📅 {today}\n"
            "No WNBA games scheduled today."
        )
        if dry_run:
            print("\n--- DRY RUN OUTPUT ---")
            print(msg)
        else:
            send_message(msg)
        return

    # 2. Get model predictions
    print("Fetching model predictions...")
    predictions = fetch_model_predictions()
    print(f"  Got {len(predictions)} prediction(s)")

    # 3. Get streaks + rest days for each team
    print("Fetching team streaks and rest days...")
    streaks = {}
    all_teams = set()
    for g in games:
        all_teams.add((g["home_team"], g["home_team_id"]))
        all_teams.add((g["away_team"], g["away_team_id"]))

    for team_name, team_id in all_teams:
        print(f"  {team_name}...")
        streaks[team_name] = fetch_team_streak(team_id)

    # 4. Get star player streaks
    print("Fetching star player streaks...")
    star_notices = {}
    for team_name, _ in all_teams:
        notices = fetch_star_player_streaks(team_name)
        if notices:
            star_notices[team_name] = notices
            print(f"  {team_name}: {len(notices)} notice(s)")

    # 5. Fetch injury reports
    injury_map = {}
    if INJURIES_ENABLED:
        print("Fetching injury reports...")
        raw_injuries = fetch_injuries("WNBA")
        # Flatten to {team_name: ["Player (Status)", ...]}
        for team, reports in raw_injuries.items():
            significant = [r for r in reports if r.status in ["Out", "Doubtful", "Day-To-Day"]]
            if significant:
                injury_map[team] = [f"{r.player} ({r.status})" for r in significant]
        print(f"  Found injuries for {len(injury_map)} team(s)")

    # 6. Fetch news headlines
    all_news = []
    if NEWS_ENABLED:
        print("Fetching news headlines...")
        all_news = fetch_all_headlines()

    # 7. Format and send
    print("Formatting digest...")
    digest = format_digest(games, predictions, streaks, star_notices, all_news=all_news, injury_map=injury_map)

    if dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        for i, msg in enumerate(digest):
            print(f"\n[Message {i+1}]")
            print(msg)
            print()
    else:
        for msg in digest:
            send_message(msg)
            time.sleep(1)
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print digest without sending to Telegram")
    args = parser.parse_args()
    run_digest(dry_run=args.dry_run)