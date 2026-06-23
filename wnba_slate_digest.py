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

try:
    from espn_winprob import get_espn_win_probs, check_divergence
    ESPN_PROB_ENABLED = True
except ImportError:
    ESPN_PROB_ENABLED = False

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
# ─────────────────────────────────────────────────────────────

WNBA_STAR_PLAYERS = {
    "Las Vegas Aces":          ["A'ja Wilson", "Chelsea Gray", "Jackie Young"],
    "New York Liberty":        ["Breanna Stewart", "Sabrina Ionescu", "Jonquel Jones", "Satou Sabally"],
    "Seattle Storm":           ["Flau'jae Johnson", "Natisha Hiedeman", "Dominique Malonga"],
    "Minnesota Lynx":          ["Napheesa Collier", "Courtney Williams", "Kayla McBride", "Olivia Miles", "Natasha Howard"],
    "Connecticut Sun":         ["Aneesah Morrow", "Brittney Griner", "Kennedy Burke", "Leila Lacan", "Aaliyah Edwards"],
    "Indiana Fever":           ["Caitlin Clark", "Aliyah Boston", "NaLyssa Smith", "Monique Billings", "Raven Johnson", "Kelsey Mitchell"],
    "Chicago Sky":             ["Kamilla Cardoso", "DiJonai Carrington", "Skylar Diggins", "Natasha Cloud", "Rickea Jackson", "Gabriela Jaquez"],
    "Atlanta Dream":           ["Rhyne Howard", "Te-Hina Paopao", "Allisha Gray", "Angel Reese", "Jordin Canada", "Naz Hillmon"],
    "Phoenix Mercury":         ["DeWanna Bonner", "Alyssa Thomas", "Natasha Mack", "Kahleah Copper"],
    "Los Angeles Sparks":      ["Cameron Brink", "Dearica Hamby", "Nneka Ogwumike", "Kelsey Plum"],
    "Washington Mystics":      ["Lauren Betts", "Rori Harmon", "Sonia Citron", "Shakira Austin"],
    "Dallas Wings":            ["Arike Ogunbowale", "Paige Bueckers", "Alysha Clark", "Azzi Fudd", "Jessica Shepard"],
    "Golden State Valkyries":  ["Kayla Thornton", "Kaila Charles", "Tiffany Hayes", "Veronica Burton"],
    "Toronto Tempo":           ["Maria Conde", "Brittney Sykes", "Marina Mabrey", "Kiki Rice", "Nyara Sabally"],
    "Portland Fire":           ["Carla Leite", "Bridget Carleton"],
}

DOUBLE_DOUBLE_GAMES = 3


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

        home_name   = home.get("team", {}).get("displayName", "")
        away_name   = away.get("team", {}).get("displayName", "")
        home_record = home.get("records", [{}])[0].get("summary", "") if home.get("records") else ""
        away_record = away.get("records", [{}])[0].get("summary", "") if away.get("records") else ""
        utc_time    = event.get("date", "")
        game_time   = format_game_time(utc_time)
        status      = event.get("status", {}).get("type", {}).get("name", "")
        completed   = event.get("status", {}).get("type", {}).get("completed", False)

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
    injuries = []
    for player in competitor.get("injuries", []):
        name   = player.get("athlete", {}).get("displayName", "")
        status = player.get("status", "")
        if name and status in ["Out", "Doubtful", "Questionable"]:
            injuries.append(f"{name} ({status})")
    return injuries


# ─────────────────────────────────────────────────────────────
# STREAK FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_team_streak(team_id: str) -> dict:
    if not team_id:
        return {"type": "", "count": 0, "rest_days": None}

    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/{team_id}/schedule"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  Streak fetch error (team {team_id}): {e}")
        return {"type": "", "count": 0, "rest_days": None}

    today  = get_today_ct()
    events = data.get("events", [])
    past   = []

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

        comp        = event.get("competitions", [{}])[0]
        competitors = comp.get("competitors", [])
        team_comp   = next((c for c in competitors if c.get("team", {}).get("id") == team_id), None)
        if not team_comp:
            continue

        winner = team_comp.get("winner", False)
        past.append({"date": game_day, "result": "W" if winner else "L"})

    if not past:
        return {"type": "", "count": 0, "rest_days": None}

    past.sort(key=lambda x: x["date"], reverse=True)
    last_game_date = past[0]["date"]
    rest_days      = (today - last_game_date).days
    streak_type    = past[0]["result"]
    streak_count   = 0

    for game in past:
        if game["result"] == streak_type:
            streak_count += 1
        else:
            break

    return {"type": streak_type, "count": streak_count, "rest_days": rest_days}


# ─────────────────────────────────────────────────────────────
# STAR PLAYER STREAK FETCHER
# ─────────────────────────────────────────────────────────────

STREAK_THRESHOLDS = [
    {"stat": "pts",     "label": "PPG",  "threshold": 20, "games": 3},
    {"stat": "reb",     "label": "RPG",  "threshold": 8,  "games": 2},
    {"stat": "ast",     "label": "APG",  "threshold": 6,  "games": 2},
    {"stat": "three",   "label": "3PG",  "threshold": 3,  "games": 2},
    {"stat": "stl",     "label": "SPG",  "threshold": 2,  "games": 2},
    {"stat": "blk",     "label": "BPG",  "threshold": 2,  "games": 2},
]


def fetch_star_player_streaks(team_name: str) -> list:
    stars   = WNBA_STAR_PLAYERS.get(team_name, [])
    notices = []

    if not stars:
        return notices

    today    = get_today_ct()
    game_ids = []

    for days_back in range(1, 20):
        check_date = (today - timedelta(days=days_back)).strftime("%Y%m%d")
        url        = f"{ESPN_WNBA_SCOREBOARD}?dates={check_date}"
        try:
            r    = requests.get(url, headers=HEADERS, timeout=8)
            data = r.json()
            for event in data.get("events", []):
                completed   = event.get("status", {}).get("type", {}).get("completed", False)
                comps       = event.get("competitions", [{}])
                competitors = comps[0].get("competitors", []) if comps else []
                team_names  = [c.get("team", {}).get("displayName", "") for c in competitors]
                if completed and team_name in team_names:
                    game_ids.append(event.get("id"))
                    if len(game_ids) >= 5:
                        break
        except:
            pass
        if len(game_ids) >= 5:
            break

    if not game_ids:
        print(f"  No recent completed games found for {team_name} star players")
        return notices

    player_logs = {star: [] for star in stars}

    for game_id in game_ids:
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
                            return float(val) if val not in ("N/A", "-", "", None) else 0.0
                        except:
                            return 0.0

                    player_logs[p_name].append({
                        "pts":   gs("points"),
                        "reb":   gs("rebounds"),
                        "ast":   gs("assists"),
                        "three": gs("threePointFieldGoalsMade"),
                        "stl":   gs("steals"),
                        "blk":   gs("blocks"),
                    })
        except Exception as e:
            print(f"  Box score error ({game_id}): {e}")
            continue

    for player, games in player_logs.items():
        if not games:
            continue

        qualified = []

        for t in STREAK_THRESHOLDS:
            stat      = t["stat"]
            label     = t["label"]
            threshold = t["threshold"]
            n_games   = t["games"]

            if len(games) < n_games:
                continue

            recent = games[:n_games]

            if all(g[stat] >= threshold for g in recent):
                avg    = round(sum(g[stat] for g in recent) / n_games, 1)
                margin = round(avg - threshold, 1)
                qualified.append({
                    "notice": f"⚡ {player}: {avg} {label} last {n_games}G",
                    "margin": margin,
                })

        if len(games) >= DOUBLE_DOUBLE_GAMES:
            recent   = games[:DOUBLE_DOUBLE_GAMES]
            dd_games = [g for g in recent if g["pts"] >= 10 and (g["reb"] >= 10 or g["ast"] >= 10)]
            if len(dd_games) == DOUBLE_DOUBLE_GAMES:
                qualified.append({
                    "notice": f"⚡ {player}: Double-double last {DOUBLE_DOUBLE_GAMES}G",
                    "margin": 99,
                })

        if len(games) >= 2:
            recent   = games[:2]
            td_games = [g for g in recent if g["pts"] >= 10 and g["reb"] >= 10 and g["ast"] >= 10]
            if len(td_games) == 2:
                qualified.append({
                    "notice": f"⚡ {player}: Triple-double last 2G",
                    "margin": 999,
                })

        qualified.sort(key=lambda x: x["margin"], reverse=True)
        for q in qualified[:2]:
            notices.append(q["notice"])

    return notices


# ─────────────────────────────────────────────────────────────
# MODEL PREDICTIONS FETCHER
# ─────────────────────────────────────────────────────────────

def fetch_model_predictions() -> dict:
    try:
        r    = requests.get(f"{API_BASE}/wnba/predictions", params={"simulations": 5000}, timeout=60)
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

        home_prob = round(float(model_prob), 1)
        away_prob = round(100 - home_prob, 1)

        predicted_winner = home_team if home_prob > away_prob else away_team
        winner_prob      = max(home_prob, away_prob)

        has_edge   = edge >= 10
        pick_label = bet_label if has_edge else ""


        predictions[game] = {
            "home_team":        home_team,
            "away_team":        away_team,
            "home_prob":        home_prob,
            "away_prob":        away_prob,
            "predicted_winner": predicted_winner,
            "winner_prob":      winner_prob,
            "edge":             edge,
            "has_edge":         has_edge,
            "pick_label":       pick_label,
            "odds":             odds,
            "implied_prob":     implied,
        }

    return predictions


# ─────────────────────────────────────────────────────────────
# MATCH ESPN GAME TO MODEL PREDICTION
# ─────────────────────────────────────────────────────────────

def match_prediction(game: dict, predictions: dict) -> dict:
    home = game["home_team"]
    away = game["away_team"]

    key = f"{away} @ {home}"

    if key in predictions:
        return predictions[key]

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


def format_digest(
    games: list,
    predictions: dict,
    streaks: dict,
    star_notices: dict,
    all_news: list = None,
    injury_map: dict = None,
    espn_probs: dict = None,
) -> list:
    today       = get_today_ct().strftime("%B %d, %Y")
    all_news    = all_news or []
    injury_map  = injury_map or {}
    espn_probs  = espn_probs or {}
    used_titles = set()
    messages    = []

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

    for g in games:
        home = g["home_team"]
        away = g["away_team"]

        pred         = match_prediction(g, predictions)
        home_streak  = streaks.get(home, {})
        away_streak  = streaks.get(away, {})
        home_notices = star_notices.get(home, [])
        away_notices = star_notices.get(away, [])

        lines = [f"🏟 <b>{away} @ {home}</b>", f"🕐 {g['game_time']}"]
        lines.append("───────────────────")

        rec = []
        if g["away_record"]: rec.append(f"{away}: {g['away_record']}")
        if g["home_record"]: rec.append(f"{home}: {g['home_record']}")
        if rec: lines.append("📋 " + " | ".join(rec))

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

        away_inj = injury_map.get(away, g.get("away_injuries", []))
        home_inj = injury_map.get(home, g.get("home_injuries", []))
        if away_inj: lines.append(f"🚑 {away}: {', '.join(away_inj)}")
        if home_inj: lines.append(f"🚑 {home}: {', '.join(home_inj)}")

        for notice in (away_notices + home_notices)[:3]:
            lines.append(notice)

        if NEWS_ENABLED and all_news:
            for h in get_game_news(home, away, all_news):
                if h not in used_titles:
                    lines.append(h)
                    used_titles.add(h)

        lines.append("───────────────────")
        if pred:
            away_prob = pred.get("away_prob", 50)
            home_prob = pred.get("home_prob", 50)
            winner    = pred.get("predicted_winner", "")
            w_prob    = pred.get("winner_prob", 50)

            game_key        = f"{away} @ {home}"
            espn_game       = espn_probs.get(game_key, {})
            divergence_line = ""
            if espn_game and ESPN_PROB_ENABLED:
                espn_home = espn_game.get("home_prob", 50)
                espn_away = espn_game.get("away_prob", 50)
                div = check_divergence(home_prob, espn_home)
                if div["diverged"]:
                    espn_winner  = home if espn_home > espn_away else away
                    model_winner = winner
                    if espn_winner != model_winner:
                        divergence_line = (
                            f"⚠️ <b>Model diverges from ESPN</b> — "
                            f"Model: {model_winner} | ESPN: {espn_winner} "
                            f"({espn_home}% home) | Gap: {div['gap']} pts"
                        )
                    else:
                        divergence_line = (
                            f"⚠️ <b>Model/ESPN gap: {div['gap']} pts</b> — "
                            f"same winner but confidence differs"
                        )

            lines.append(f"📊 Model: {away} {away_prob}% | {home} {home_prob}%")
            if espn_game:
                lines.append(f"📊 ESPN:  {away} {espn_game.get('away_prob', '?')}% | {home} {espn_game.get('home_prob', '?')}%")
            lines.append(f"🤖 <b>Model Pick: {winner} ({w_prob}%)</b>")
            if divergence_line:
                lines.append(divergence_line)
            if pred.get("has_edge") and pred.get("pick_label"):
                try:
                    from database import log_prediction
                    log_prediction({
                        "game":          f"{away} @ {home}",
                        "bet":           pred.get("pick_label", ""),
                        "odds":          pred.get("odds"),
                        "model_prob":    pred.get("winner_prob", 0),
                        "implied_prob":  pred.get("implied_prob", 52.4),
                        "edge":          round(pred.get("edge", 0) / 100, 4),
                        "home_record":   g.get("home_record", ""),
                        "away_record":   g.get("away_record", ""),
                        "home_rest":     None,
                        "away_rest":     None,
                        "home_injuries": ", ".join(g.get("home_injuries", [])),
                        "away_injuries": ", ".join(g.get("away_injuries", [])),
                    }, "wnba")
                except Exception as e:
                    print(f"  Prediction log error: {e}")
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

    print("Fetching model predictions...")
    predictions = fetch_model_predictions()
    print(f"  Got {len(predictions)} prediction(s)")

    print("Fetching team streaks and rest days...")
    streaks   = {}
    all_teams = set()
    for g in games:
        all_teams.add((g["home_team"], g["home_team_id"]))
        all_teams.add((g["away_team"], g["away_team_id"]))

    for team_name, team_id in all_teams:
        print(f"  {team_name}...")
        streaks[team_name] = fetch_team_streak(team_id)

    print("Fetching star player streaks...")
    star_notices = {}
    for team_name, _ in all_teams:
        notices = fetch_star_player_streaks(team_name)
        if notices:
            star_notices[team_name] = notices
            print(f"  {team_name}: {len(notices)} notice(s)")

    espn_probs = {}
    if ESPN_PROB_ENABLED:
        print("Fetching ESPN win probabilities...")
        espn_probs = get_espn_win_probs("WNBA")
        print(f"  Got ESPN probs for {len(espn_probs)} game(s)")

    injury_map = {}
    if INJURIES_ENABLED:
        print("Fetching injury reports...")
        raw_injuries = fetch_injuries("WNBA")
        for team, reports in raw_injuries.items():
            significant = [r for r in reports if r.status in ["Out", "Doubtful", "Day-To-Day"]]
            if significant:
                injury_map[team] = [f"{r.player} ({r.status})" for r in significant]
        print(f"  Found injuries for {len(injury_map)} team(s)")

    all_news = []
    if NEWS_ENABLED:
        print("Fetching news headlines...")
        all_news = fetch_all_headlines()

    print("Formatting digest...")
    digest = format_digest(
        games,
        predictions,
        streaks,
        star_notices,
        all_news=all_news,
        injury_map=injury_map,
        espn_probs=espn_probs,
    )

    if dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        for i, msg in enumerate(digest):
            print(f"\n[Message {i+1}]")
            print(msg)
            print()
    else:
        for msg in digest:
            send_message(msg)
            time.sleep(2)
        print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print digest without sending to Telegram")
    args = parser.parse_args()
    run_digest(dry_run=args.dry_run)