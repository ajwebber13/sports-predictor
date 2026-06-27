"""
wnba_slate_digest.py — Culture & Pulse Analytics
=================================================
Sends a full WNBA daily slate digest to Telegram BEFORE edge alerts fire.
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

WNBA_STAR_PLAYERS = {
    "Atlanta Dream":             ["Rhyne Howard", "Angel Reese", "Allisha Gray", "Te-Hina Paopao", "Jordin Canada", "Isobel Borlase"],
    "Chicago Sky":               ["Kamilla Cardoso", "Skylar Diggins", "Natasha Cloud", "Rachel Banham", "DiJonai Carrington", "Aicha Coulibaly"],
    "Connecticut Sun":           ["Brittney Griner", "Leila Lacan", "Aaliyah Edwards", "Nell Angloma", "Raegan Beers", "Kennedy Burke"],
    "Dallas Wings":              ["Arike Ogunbowale", "Paige Bueckers", "Azzi Fudd", "Alysha Clark", "Aziaha James", "Haley Jones"],
    "Golden State Valkyries":    ["Tiffany Hayes", "Kayla Thornton", "Veronica Burton", "Laeticia Amihere", "Kaila Charles", "Kaitlyn Chen"],
    "Indiana Fever":             ["Caitlin Clark", "Aliyah Boston", "Kelsey Mitchell", "Monique Billings", "Sophie Cunningham", "Damiris Dantas"],
    "Las Vegas Aces":            ["A'ja Wilson", "Jackie Young", "Chennedy Carter", "Janiah Barker", "Kierstan Bell", "Dana Evans"],
    "Los Angeles Sparks":        ["Dearica Hamby", "Kelsey Plum", "Nneka Ogwumike", "Kate Martin", "Ariel Atkins", "Cameron Brink"],
    "Minnesota Lynx":            ["Napheesa Collier", "Kayla McBride", "Olivia Miles", "Maya Caldwell", "Emma Cechova", "Nia Coffey"],
    "New York Liberty":          ["Breanna Stewart", "Sabrina Ionescu", "Jonquel Jones", "Satou Sabally", "Rebecca Allen", "Pauline Astier"],
    "Phoenix Mercury":           ["Alyssa Thomas", "DeWanna Bonner", "Kahleah Copper", "Natasha Mack", "Monique Akoa Makani", "Valeriane Ayayi"],
    "Portland Fire":             ["Carla Leite", "Bridget Carleton", "Sarah Ashlee Barker", "Frieda Buhner", "Emily Engstler", "Sania Feagin"],
    "Seattle Storm":             ["Zia Cooke", "Stefanie Dolson", "Awa Fam", "Natisha Hiedeman", "Mackenzie Holmes", "Jordan Horston"],
    "Toronto Tempo":             ["Marina Mabrey", "Kiki Rice", "Julie Allemand", "Maria Conde", "Temi Fagbenle", "Isabelle Harrison"],
    "Washington Mystics":        ["Shakira Austin", "Lauren Betts", "Rori Harmon", "Georgia Amoore", "Sonia Citron", "Angela Dugalic"],
}

DOUBLE_DOUBLE_GAMES = 3


def get_today_ct() -> datetime.date:
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def format_game_time(utc_str: str) -> str:
    try:
        utc_dt     = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        return central_dt.strftime("%I:%M %p CT").lstrip("0")
    except:
        return "TBD"


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
    past   = []
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
    rest_days    = (today - past[0]["date"]).days
    streak_type  = past[0]["result"]
    streak_count = 0
    for game in past:
        if game["result"] == streak_type:
            streak_count += 1
        else:
            break
    return {"type": streak_type, "count": streak_count, "rest_days": rest_days}


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


def fetch_model_predictions(expected_games: int = 0) -> dict:
    max_retries = 3
    retry_delay = 30  # seconds
    predictions = {}

    for attempt in range(1, max_retries + 1):
        try:
            r    = requests.get(f"{API_BASE}/wnba/predictions", params={"simulations": 5000}, timeout=60)
            data = r.json()
        except Exception as e:
            print(f"Model API error (attempt {attempt}): {e}")
            if attempt < max_retries:
                print(f"  Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            continue

        predictions = {}
        for bet in data.get("best_bets", []):
            game       = bet.get("game", "")
            model_prob = bet.get("model_prob", 50)
            edge       = round(bet.get("edge", 0) * 100, 1)
            bet_label  = bet.get("bet", "")
            odds       = bet.get("odds")
            implied    = bet.get("implied_prob", 50)
            parts      = game.split(" @ ")
            home_team  = parts[1] if len(parts) == 2 else ""
            away_team  = parts[0] if len(parts) == 2 else ""
            home_prob  = round(float(model_prob), 1)
            away_prob  = round(100 - home_prob, 1)
            predicted_winner = home_team if home_prob > away_prob else away_team
            winner_prob      = max(home_prob, away_prob)
            has_edge   = edge >= 8
            pick_label = bet_label if has_edge else ""
            predictions[game] = {
                "home_team":          home_team,
                "away_team":          away_team,
                "home_prob":          home_prob,
                "away_prob":          away_prob,
                "predicted_winner":   predicted_winner,
                "winner_prob":        winner_prob,
                "edge":               edge,
                "has_edge":           has_edge,
                "pick_label":         pick_label,
                "odds":               odds,
                "implied_prob":       implied,
                "projected":          bet.get("projected", ""),
                "pred_margin":        bet.get("pred_margin"),
                "posted_spread":      bet.get("posted_spread"),
                "spread_pick":        bet.get("spread_pick"),
                "spread_cover_prob":  bet.get("spread_cover_prob"),
                "spread_edge":        bet.get("spread_edge"),
                "projected_total":    bet.get("projected_total"),
                "posted_total":       bet.get("posted_total"),
                "over_prob":          bet.get("over_prob"),
                "under_prob":         bet.get("under_prob"),
            }

        got = len(predictions)
        print(f"  Got {got} prediction(s) (attempt {attempt})")

        if expected_games == 0 or got >= expected_games:
            return predictions

        if attempt < max_retries:
            print(f"  Expected {expected_games}, got {got} — retrying in {retry_delay}s...")
            time.sleep(retry_delay)

    return predictions


def match_prediction(game: dict, predictions: dict) -> dict:
    home = game["home_team"]
    away = game["away_team"]
    key  = f"{away} @ {home}"
    if key in predictions:
        return predictions[key]
    for pred_key, pred in predictions.items():
        if pred["home_team"] in home or home in pred["home_team"]:
            if pred["away_team"] in away or away in pred["away_team"]:
                return pred
    return {}


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
    line_movement_map: dict = None,
    prop_picks_map: dict = None,
) -> list:
    today       = get_today_ct().strftime("%B %d, %Y")
    all_news    = all_news or []
    injury_map  = injury_map or {}
    espn_probs  = espn_probs or {}
    line_movement_map = line_movement_map or {}
    prop_picks_map    = prop_picks_map or {}
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

        # ── Prop picks for this game ──
        game_props = prop_picks_map.get(home, []) + prop_picks_map.get(away, [])
        if game_props:
            lines.append("🎯 <b>Prop Picks</b>")
            for prop in game_props[:4]:
                stat_label = {"pts": "PTS", "reb": "REB", "ast": "AST", "stl": "STL", "blk": "BLK"}.get(prop["stat"], prop["stat"].upper())
                tier_emoji = "✅" if prop["confidence_tier"] == "green" else "⚠️"
                hr         = prop.get("hit_rate_overall")
                hr_str     = f"{hr}%" if hr else "?"
                lines.append(f"  {tier_emoji} {prop['player_name']} o{prop['line']} {stat_label} — {hr_str}")

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

            game_key = f"{away} @ {home}"

            # ── Line movement signal ──
            lm = line_movement_map.get(game_key, {})
            if lm:
                open_h  = lm.get("opening_home_ml")
                close_h = lm.get("closing_home_ml")
                open_a  = lm.get("opening_away_ml")
                close_a = lm.get("closing_away_ml")
                sharp   = lm.get("sharp_signal", "")
                if open_h and close_h:
                    lines.append(
                        f"📉 Line: {home} {open_h:+d}→{close_h:+d} | "
                        f"{away} {open_a:+d}→{close_a:+d}"
                    )
                if sharp:
                    lines.append(f"🔔 {sharp}")

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

            # Log ALL predictions to DB for tracking and calibration
            try:
                from database import log_prediction
                log_prediction({
                    "game":          f"{away} @ {home}",
                    "bet":           pred.get("pick_label") or pred.get("predicted_winner", "") + " ML",
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

            # ── Confidence tier ──
            w_prob_val = pred.get("winner_prob", 0)
            edge_val   = pred.get("edge", 0)
            if w_prob_val >= 60 and edge_val >= 10:
                conf_tier  = "green"
                tier_emoji = "🟢"
            elif w_prob_val >= 55 or (edge_val >= 8 and edge_val < 10):
                conf_tier  = "yellow"
                tier_emoji = "🟡"
            else:
                conf_tier  = "red"
                tier_emoji = "🔴"

            if pred.get("has_edge") and pred.get("pick_label"):
                pick_team = pred["pick_label"].replace(" ML", "").strip()
                pick_injuries = []
                if pick_team == home:
                    pick_injuries = injury_map.get(home, g.get("home_injuries", []))
                elif pick_team == away:
                    pick_injuries = injury_map.get(away, g.get("away_injuries", []))
                star_list = WNBA_STAR_PLAYERS.get(pick_team, [])
                star_out_count = sum(
                    1 for inj in pick_injuries
                    if ("(Out)" in inj or "(Doubtful)" in inj)
                    and any(star.lower() in inj.lower() for star in star_list)
                )
                if star_out_count >= 2:
                    lines.append(f"⚠️ Edge suppressed — {pick_team} missing {star_out_count} key players")
                else:
                    # ── B2B check — downgrade GREEN to YELLOW if pick team is on a back-to-back ──
                    pick_streak = streaks.get(pick_team, {})
                    pick_rest   = pick_streak.get("rest_days")
                    if pick_rest == 0 and conf_tier == "green":
                        conf_tier  = "yellow"
                        tier_emoji = "🟡"
                        lines.append(f"{tier_emoji} <b>EDGE PICK: {pred['pick_label']} | +{pred.get('edge', 0)}% ({conf_tier.upper()})</b>")
                        lines.append(f"⚠️ Downgraded — {pick_team} on a back-to-back")
                    else:
                        lines.append(f"{tier_emoji} <b>EDGE PICK: {pred['pick_label']} | +{pred.get('edge', 0)}% ({conf_tier.upper()})</b>")
                        if pick_rest == 0:
                            lines.append(f"⚠️ Note — {pick_team} on a back-to-back")

                    # Spread pick — show only if cover prob 60%+
                    spread_pick   = pred.get("spread_pick")
                    spread_prob   = pred.get("spread_cover_prob")
                    spread_edge   = pred.get("spread_edge")
                    posted_spread = pred.get("posted_spread")
                    pred_margin   = pred.get("pred_margin")
                    if spread_pick and spread_prob and posted_spread is not None and pred_margin is not None and spread_prob >= 60:
                        lines.append(
                            f"📐 <b>SPREAD: {spread_pick} | {spread_prob}% cover</b> "
                            f"(model margin {pred_margin:+.1f} vs posted {posted_spread:+.1f})"
                        )

                    # Totals pick — fire when edge is 4-15 pts
                    proj_total   = pred.get("projected_total")
                    posted_total = pred.get("posted_total")
                    over_prob    = pred.get("over_prob")
                    under_prob   = pred.get("under_prob")
                    if proj_total and posted_total:
                        total_edge = round(proj_total - posted_total, 1)
                        if abs(total_edge) >= 4 and abs(total_edge) <= 15:
                            if total_edge > 0:
                                direction  = "OVER"
                                total_prob = over_prob
                            else:
                                direction  = "UNDER"
                                total_prob = under_prob
                            lines.append(
                                f"🎯 <b>TOTAL: {direction} {posted_total} | {total_prob}%</b> "
                                f"(model projects {proj_total}, edge {total_edge:+.1f})"
                            )
            else:
                lines.append(f"🔴 No edge pick (below threshold)")

                projected    = pred.get("projected", "")
                proj_total   = pred.get("projected_total")
                posted_total = pred.get("posted_total")
                if projected:
                    lines.append(f"📐 Projected: {projected}")
                if proj_total and posted_total:
                    total_edge = round(proj_total - posted_total, 1)
                    direction  = "OVER" if total_edge > 0 else "UNDER"
                    if abs(total_edge) >= 4 and abs(total_edge) <= 15:
                        lines.append(f"🎯 Total lean: {direction} {posted_total} (model {proj_total}, edge {total_edge:+.1f})")
        else:
            lines.append("📊 Model prediction unavailable")

        lines.append("")
        lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
        messages.append("\n".join(lines))

    return messages


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
    predictions = fetch_model_predictions(expected_games=len(games))
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

    # ── Today's prop picks ──
    prop_picks_map = {}
    try:
        import sqlite3 as _sqlite3
        _db   = os.path.join(os.path.dirname(__file__), "cp_analytics.db")
        _conn = _sqlite3.connect(_db)
        _conn.row_factory = _sqlite3.Row
        _c    = _conn.cursor()
        _today = get_today_ct().strftime("%Y-%m-%d")
        _c.execute("""
            SELECT player_name, team_name, stat, line,
                   over_odds, under_odds,
                   hit_rate_overall, confidence_tier
            FROM player_props
            WHERE date = ? AND sport = ? AND confidence_tier IN ('green', 'yellow')
            ORDER BY hit_rate_overall DESC
        """, (_today, "wnba"))
        all_props_today = [dict(r) for r in _c.fetchall()]
        _c.execute("""
            SELECT player_name, team_name
            FROM wnba_game_log
            WHERE team_name != ''
            GROUP BY player_name
            ORDER BY date DESC
        """)
        player_team_map = {r["player_name"]: r["team_name"] for r in _c.fetchall()}
        _conn.close()
        for prop in all_props_today:
            team = prop.get("team_name") or player_team_map.get(prop["player_name"], "")
            prop["team_name"] = team
            if team:
                if team not in prop_picks_map:
                    prop_picks_map[team] = []
                prop_picks_map[team].append(prop)
        if prop_picks_map:
            total = sum(len(v) for v in prop_picks_map.values())
            print(f"  Loaded {total} prop pick(s) for {len(prop_picks_map)} team(s)")
    except Exception as e:
        print(f"  Prop picks load error (non-fatal): {e}")

    # ── Line movement ──
    line_movement_map = {}
    try:
        import sqlite3 as _sqlite3
        _db = os.path.join(os.path.dirname(__file__), "cp_analytics.db")
        _conn = _sqlite3.connect(_db)
        _conn.row_factory = _sqlite3.Row
        _c = _conn.cursor()
        _today = get_today_ct().strftime("%Y-%m-%d")
        _c.execute("""
            SELECT home_team, away_team, opening_home_ml, opening_away_ml,
                   closing_home_ml, closing_away_ml,
                   movement_home, movement_away, sharp_signal
            FROM line_movement
            WHERE date = ? AND sport = ?
        """, (_today, "wnba"))
        for row in _c.fetchall():
            key = f"{row['away_team']} @ {row['home_team']}"
            line_movement_map[key] = dict(row)
        _conn.close()
        if line_movement_map:
            print(f"  Loaded line movement for {len(line_movement_map)} game(s)")
    except Exception as e:
        print(f"  Line movement load error (non-fatal): {e}")

    print("Formatting digest...")
    digest = format_digest(
        games,
        predictions,
        streaks,
        star_notices,
        all_news=all_news,
        injury_map=injury_map,
        espn_probs=espn_probs,
        line_movement_map=line_movement_map,
        prop_picks_map=prop_picks_map,
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