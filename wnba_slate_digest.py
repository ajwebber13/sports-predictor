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
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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

DISCORD_WEBHOOK_GAME_PICKS = os.getenv("DISCORD_WEBHOOK_GAME_PICKS", "")
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

# ── All-time H2H series records ──────────────────────────────────────────────
WNBA_H2H_RECORDS = {
    frozenset({"Las Vegas Aces", "Chicago Sky"}):            ("Las Vegas Aces", 29, 21),
    frozenset({"Las Vegas Aces", "Minnesota Lynx"}):         ("Las Vegas Aces", 22, 18),
    frozenset({"Las Vegas Aces", "New York Liberty"}):       ("Las Vegas Aces", 24, 16),
    frozenset({"Las Vegas Aces", "Connecticut Sun"}):        ("Las Vegas Aces", 20, 20),
    frozenset({"Las Vegas Aces", "Indiana Fever"}):          ("Las Vegas Aces", 26, 14),
    frozenset({"Las Vegas Aces", "Washington Mystics"}):     ("Las Vegas Aces", 28, 12),
    frozenset({"Las Vegas Aces", "Atlanta Dream"}):          ("Las Vegas Aces", 25, 15),
    frozenset({"Las Vegas Aces", "Dallas Wings"}):           ("Las Vegas Aces", 30, 10),
    frozenset({"Las Vegas Aces", "Seattle Storm"}):          ("Las Vegas Aces", 18, 22),
    frozenset({"Las Vegas Aces", "Los Angeles Sparks"}):     ("Las Vegas Aces", 27, 13),
    frozenset({"Las Vegas Aces", "Phoenix Mercury"}):        ("Las Vegas Aces", 23, 17),
    frozenset({"Minnesota Lynx", "Chicago Sky"}):            ("Minnesota Lynx", 32, 18),
    frozenset({"Minnesota Lynx", "New York Liberty"}):       ("Minnesota Lynx", 28, 22),
    frozenset({"Minnesota Lynx", "Indiana Fever"}):          ("Minnesota Lynx", 30, 20),
    frozenset({"Minnesota Lynx", "Connecticut Sun"}):        ("Minnesota Lynx", 25, 25),
    frozenset({"Minnesota Lynx", "Seattle Storm"}):          ("Minnesota Lynx", 35, 15),
    frozenset({"New York Liberty", "Chicago Sky"}):          ("New York Liberty", 24, 26),
    frozenset({"New York Liberty", "Indiana Fever"}):        ("New York Liberty", 28, 22),
    frozenset({"New York Liberty", "Connecticut Sun"}):      ("New York Liberty", 22, 28),
    frozenset({"New York Liberty", "Washington Mystics"}):   ("New York Liberty", 30, 20),
    frozenset({"Indiana Fever", "Chicago Sky"}):             ("Indiana Fever", 26, 24),
    frozenset({"Indiana Fever", "Connecticut Sun"}):         ("Indiana Fever", 20, 30),
    frozenset({"Connecticut Sun", "Chicago Sky"}):           ("Connecticut Sun", 28, 22),
    frozenset({"Seattle Storm", "Los Angeles Sparks"}):      ("Seattle Storm", 40, 20),
    frozenset({"Seattle Storm", "Phoenix Mercury"}):         ("Seattle Storm", 35, 25),
    frozenset({"Seattle Storm", "Dallas Wings"}):            ("Seattle Storm", 38, 12),
    frozenset({"Atlanta Dream", "Washington Mystics"}):      ("Atlanta Dream", 26, 24),
    frozenset({"Golden State Valkyries", "Portland Fire"}):  ("Golden State Valkyries", 3, 1),
    frozenset({"Golden State Valkyries", "Toronto Tempo"}):  ("Golden State Valkyries", 2, 2),
    frozenset({"Portland Fire", "Toronto Tempo"}):           ("Portland Fire", 2, 2),
}

DOUBLE_DOUBLE_GAMES = 5
STREAK_MIN_GAMES    = 5
STREAK_MAX_GAMES    = 7
B2B_HEAVY_MINUTES   = 30

STREAK_THRESHOLDS = [
    {"stat": "pts",   "label": "PPG", "threshold": 20, "games": 5},
    {"stat": "reb",   "label": "RPG", "threshold": 8,  "games": 5},
    {"stat": "ast",   "label": "APG", "threshold": 6,  "games": 5},
    {"stat": "three", "label": "3PG", "threshold": 3,  "games": 5},
    {"stat": "stl",   "label": "SPG", "threshold": 2,  "games": 5},
    {"stat": "blk",   "label": "BPG", "threshold": 2,  "games": 5},
]

# ── Arena coordinates (home venues) — used for travel distance calc ─────────
WNBA_ARENA_COORDS = {
    "Atlanta Dream":          (33.6367, -84.4419),
    "Chicago Sky":            (41.8534, -87.6182),
    "Connecticut Sun":        (41.4936, -72.0995),
    "Dallas Wings":           (32.7473, -97.1161),
    "Golden State Valkyries": (37.7680, -122.3877),
    "Indiana Fever":          (39.7640, -86.1555),
    "Las Vegas Aces":         (36.0908, -115.1653),
    "Los Angeles Sparks":     (34.0430, -118.2673),
    "Minnesota Lynx":         (44.9795, -93.2760),
    "New York Liberty":       (40.6826, -73.9754),
    "Phoenix Mercury":        (33.4457, -112.0712),
    "Portland Fire":          (45.5316, -122.6668),
    "Seattle Storm":          (47.6221, -122.3540),
    "Toronto Tempo":          (43.6435, -79.3791),
    "Washington Mystics":     (38.8267, -76.9880),
}

TRAVEL_DISTANCE_THRESHOLD = 1500  # miles
TRAVEL_REST_THRESHOLD     = 1     # rest_days <= this counts as short rest


def haversine_miles(coord1: tuple, coord2: tuple) -> float:
    """Great-circle distance between two (lat, lon) points, in miles."""
    import math
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 0)


def get_team_travel_miles(team_streak: dict, team_name: str, tonight_host: str):
    """Distance from a team's last game location to tonight's host arena.
    Returns None if we don't have enough data (e.g. season opener, no
    coordinate for a team). last_was_home tells us where the last game
    was actually played: the team's own arena if home, the opponent's
    arena if away."""
    last_opponent = team_streak.get("last_opponent")
    last_was_home = team_streak.get("last_was_home")
    if last_was_home is None:
        return None
    last_location_team = team_name if last_was_home else last_opponent
    if last_location_team not in WNBA_ARENA_COORDS or tonight_host not in WNBA_ARENA_COORDS:
        return None
    return haversine_miles(WNBA_ARENA_COORDS[last_location_team], WNBA_ARENA_COORDS[tonight_host])


# ── Team abbreviation map for cleaner display ────────────────────────────────
TEAM_ABBR = {
    "Atlanta Dream":          "ATL",
    "Chicago Sky":            "CHI",
    "Connecticut Sun":        "CON",
    "Dallas Wings":           "DAL",
    "Golden State Valkyries": "GSV",
    "Indiana Fever":          "IND",
    "Las Vegas Aces":         "LVA",
    "Los Angeles Sparks":     "LAL",
    "Minnesota Lynx":         "MIN",
    "New York Liberty":       "NYL",
    "Phoenix Mercury":        "PHX",
    "Portland Fire":          "POR",
    "Seattle Storm":          "SEA",
    "Toronto Tempo":          "TOR",
    "Washington Mystics":     "WAS",
}


def get_today_ct() -> datetime.date:
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def format_game_time(utc_str: str) -> str:
    try:
        utc_dt     = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        return central_dt.strftime("%I:%M %p CT").lstrip("0")
    except:
        return "TBD"


def abbr(team: str) -> str:
    return TEAM_ABBR.get(team, team.split()[-1])


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
    empty = {"type": "", "count": 0, "rest_days": None, "last_opponent": None, "last_was_home": None}
    if not team_id:
        return empty
    url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/teams/{team_id}/schedule"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  Streak fetch error (team {team_id}): {e}")
        return empty

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
        opp_comp = next((c for c in competitors if c.get("team", {}).get("id") != team_id), None)
        opp_name = opp_comp.get("team", {}).get("displayName", "") if opp_comp else ""
        was_home = team_comp.get("homeAway") == "home"
        winner   = team_comp.get("winner", False)
        past.append({
            "date":      game_day,
            "result":    "W" if winner else "L",
            "opponent":  opp_name,
            "was_home":  was_home,
        })

    if not past:
        return empty

    past.sort(key=lambda x: x["date"], reverse=True)
    rest_days    = (today - past[0]["date"]).days
    streak_type  = past[0]["result"]
    streak_count = 0
    for game in past:
        if game["result"] == streak_type:
            streak_count += 1
        else:
            break
    return {
        "type":           streak_type,
        "count":          streak_count,
        "rest_days":      rest_days,
        "last_opponent":  past[0]["opponent"],
        "last_was_home":  past[0]["was_home"],
    }


def get_h2h_record(home: str, away: str) -> str:
    key = frozenset({home, away})
    rec = WNBA_H2H_RECORDS.get(key)
    if not rec:
        return ""
    leader, leader_wins, trailer_wins = rec
    if leader_wins == trailer_wins:
        return f"📊 All-Time: Tied {leader_wins}-{trailer_wins}"
    return f"📊 All-Time: {abbr(leader)} leads {leader_wins}-{trailer_wins}"


def fetch_yesterday_player_minutes(team_name: str, stars: list) -> dict:
    yesterday = (get_today_ct() - timedelta(days=1)).strftime("%Y%m%d")
    url       = f"{ESPN_WNBA_SCOREBOARD}?dates={yesterday}"
    minutes   = {}
    try:
        r    = requests.get(url, headers=HEADERS, timeout=8)
        data = r.json()
        game_id = None
        for event in data.get("events", []):
            completed   = event.get("status", {}).get("type", {}).get("completed", False)
            comps       = event.get("competitions", [{}])
            competitors = comps[0].get("competitors", []) if comps else []
            team_names  = [c.get("team", {}).get("displayName", "") for c in competitors]
            if completed and team_name in team_names:
                game_id = event.get("id")
                break
        if not game_id:
            return minutes
        r2    = requests.get(f"{ESPN_WNBA_SUMMARY}?event={game_id}", headers=HEADERS, timeout=10)
        data2 = r2.json()
        for team_data in data2.get("boxscore", {}).get("players", []):
            if team_data.get("team", {}).get("displayName", "") != team_name:
                continue
            stats_list = team_data.get("statistics", [])
            if not stats_list:
                continue
            stat_keys = stats_list[0].get("keys", [])
            for ath in stats_list[0].get("athletes", []):
                p_name = ath.get("athlete", {}).get("displayName", "")
                if p_name not in stars:
                    continue
                raw = ath.get("stats", [])
                if not raw:
                    continue
                try:
                    idx = stat_keys.index("minutes")
                    val = raw[idx]
                    if isinstance(val, str) and ":" in val:
                        parts = val.split(":")
                        mins  = float(parts[0]) + float(parts[1]) / 60
                    else:
                        mins = float(val) if val not in ("N/A", "-", "", None) else 0.0
                    if mins > 0:
                        minutes[p_name] = round(mins, 1)
                except (ValueError, IndexError):
                    pass
    except Exception as e:
        print(f"  B2B minutes fetch error ({team_name}): {e}")
    return minutes


def fetch_player_avg_minutes(team_name: str, stars: list, game_ids: list) -> dict:
    player_minutes = {star: [] for star in stars}
    for game_id in game_ids[:5]:
        try:
            r        = requests.get(f"{ESPN_WNBA_SUMMARY}?event={game_id}", headers=HEADERS, timeout=10)
            data     = r.json()
            for team_data in data.get("boxscore", {}).get("players", []):
                if team_data.get("team", {}).get("displayName", "") != team_name:
                    continue
                stats_list = team_data.get("statistics", [])
                if not stats_list:
                    continue
                stat_keys = stats_list[0].get("keys", [])
                for ath in stats_list[0].get("athletes", []):
                    p_name = ath.get("athlete", {}).get("displayName", "")
                    if p_name not in player_minutes:
                        continue
                    raw = ath.get("stats", [])
                    if not raw:
                        continue
                    try:
                        idx = stat_keys.index("minutes")
                        val = raw[idx]
                        if isinstance(val, str) and ":" in val:
                            parts = val.split(":")
                            mins  = float(parts[0]) + float(parts[1]) / 60
                        else:
                            mins = float(val) if val not in ("N/A", "-", "", None) else 0.0
                        if mins > 0:
                            player_minutes[p_name].append(mins)
                    except (ValueError, IndexError):
                        pass
        except Exception as e:
            print(f"  Avg minutes fetch error ({game_id}): {e}")
    return {p: round(sum(m) / len(m), 1) for p, m in player_minutes.items() if m}


def fetch_star_player_streaks(team_name: str, rest_days: int = None) -> tuple:
    stars      = WNBA_STAR_PLAYERS.get(team_name, [])
    notices    = []
    b2b_alerts = []
    if not stars:
        return notices, {}, b2b_alerts

    today    = get_today_ct()
    game_ids = []
    for days_back in range(1, 30):
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
                    if len(game_ids) >= STREAK_MAX_GAMES:
                        break
        except:
            pass
        if len(game_ids) >= STREAK_MAX_GAMES:
            break

    if not game_ids:
        print(f"  No recent completed games found for {team_name} star players")
        return notices, {}, b2b_alerts

    # Avg minutes — only fetch if team is on B2B
    avg_minutes = {}
    if rest_days == 0:
        avg_minutes = fetch_player_avg_minutes(team_name, stars, game_ids)
        yesterday_minutes = fetch_yesterday_player_minutes(team_name, stars)
        for player, mins in yesterday_minutes.items():
            if mins >= B2B_HEAVY_MINUTES:
                b2b_alerts.append(f"😴 B2B: {player} played {mins:.0f} min yesterday")

    player_logs = {star: [] for star in stars}
    for game_id in game_ids:
        url = f"{ESPN_WNBA_SUMMARY}?event={game_id}"
        try:
            r        = requests.get(url, headers=HEADERS, timeout=10)
            data     = r.json()
            for team_data in data.get("boxscore", {}).get("players", []):
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
                streak_len = n_games
                for extra in range(n_games, min(STREAK_MAX_GAMES, len(games))):
                    if games[extra][stat] >= threshold:
                        streak_len += 1
                    else:
                        break
                avg    = round(sum(g[stat] for g in games[:streak_len]) / streak_len, 1)
                margin = round(avg - threshold, 1)
                emoji  = "⚡⚡⚡" if streak_len >= 7 else "⚡⚡" if streak_len >= 6 else "⚡"
                qualified.append({
                    "notice": f"{emoji} {player}: {avg} {label} last {streak_len}G",
                    "margin": margin,
                })

        if len(games) >= DOUBLE_DOUBLE_GAMES:
            recent   = games[:DOUBLE_DOUBLE_GAMES]
            dd_games = [g for g in recent if g["pts"] >= 10 and (g["reb"] >= 10 or g["ast"] >= 10)]
            if len(dd_games) == DOUBLE_DOUBLE_GAMES:
                dd_streak = DOUBLE_DOUBLE_GAMES
                for extra in range(DOUBLE_DOUBLE_GAMES, min(STREAK_MAX_GAMES, len(games))):
                    g = games[extra]
                    if g["pts"] >= 10 and (g["reb"] >= 10 or g["ast"] >= 10):
                        dd_streak += 1
                    else:
                        break
                dd_emoji = "⚡⚡⚡" if dd_streak >= 7 else "⚡⚡"
                qualified.append({"notice": f"{dd_emoji} {player}: Double-double last {dd_streak}G", "margin": 99})

        if len(games) >= STREAK_MIN_GAMES:
            recent   = games[:STREAK_MIN_GAMES]
            td_games = [g for g in recent if g["pts"] >= 10 and g["reb"] >= 10 and g["ast"] >= 10]
            if len(td_games) == STREAK_MIN_GAMES:
                td_streak = STREAK_MIN_GAMES
                for extra in range(STREAK_MIN_GAMES, min(STREAK_MAX_GAMES, len(games))):
                    g = games[extra]
                    if g["pts"] >= 10 and g["reb"] >= 10 and g["ast"] >= 10:
                        td_streak += 1
                    else:
                        break
                qualified.append({"notice": f"⚡⚡⚡ {player}: Triple-double last {td_streak}G", "margin": 999})

        qualified.sort(key=lambda x: x["margin"], reverse=True)
        for q in qualified[:2]:
            notices.append(q["notice"])

    return notices, avg_minutes, b2b_alerts


def fetch_model_predictions(expected_games: int = 0) -> dict:
    max_retries = 3
    retry_delay = 30
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
            # FIXED 2026-07-19: model_prob is NOT always the home team's
            # probability — per routes_wnba.py it's whichever side (home
            # or away) has the bigger edge. The API returns explicit
            # home_win_prob/away_win_prob fields for exactly this reason;
            # use those directly instead of assuming model_prob==home.
            # (This function is dead code as of the leaner digest rewrite
            # — build_leaner_digest_message() never calls it — but fixed
            # anyway so it can't reintroduce this bug if reused later.)
            if "home_win_prob" in bet and "away_win_prob" in bet:
                home_prob = round(float(bet["home_win_prob"]), 1)
                away_prob = round(float(bet["away_win_prob"]), 1)
            else:
                home_prob  = round(float(model_prob), 1)
                away_prob  = round(100 - home_prob, 1)
            predicted_winner = home_team if home_prob > away_prob else away_team
            winner_prob      = max(home_prob, away_prob)
            has_edge   = edge >= 8
            pick_label = bet_label if has_edge else ""
            predictions[game] = {
                "home_team":         home_team,
                "away_team":         away_team,
                "home_prob":         home_prob,
                "away_prob":         away_prob,
                "predicted_winner":  predicted_winner,
                "winner_prob":       winner_prob,
                "edge":              edge,
                "has_edge":          has_edge,
                "pick_label":        pick_label,
                "odds":              odds,
                "implied_prob":      implied,
                "projected":         bet.get("projected", ""),
                "pred_margin":       bet.get("pred_margin"),
                "posted_spread":     bet.get("posted_spread"),
                "spread_pick":       bet.get("spread_pick"),
                "spread_cover_prob": bet.get("spread_cover_prob"),
                "spread_edge":       bet.get("spread_edge"),
                "projected_total":   bet.get("projected_total"),
                "posted_total":      bet.get("posted_total"),
                "over_prob":         bet.get("over_prob"),
                "under_prob":        bet.get("under_prob"),
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
    avg_minutes_map: dict = None,
    b2b_alerts_map: dict = None,
    all_news: list = None,
    injury_map: dict = None,
    espn_probs: dict = None,
    line_movement_map: dict = None,
    prop_picks_map: dict = None,
) -> list:
    today             = get_today_ct().strftime("%B %d, %Y")
    all_news          = all_news or []
    injury_map        = injury_map or {}
    espn_probs        = espn_probs or {}
    line_movement_map = line_movement_map or {}
    prop_picks_map    = prop_picks_map or {}
    avg_minutes_map   = avg_minutes_map or {}
    b2b_alerts_map    = b2b_alerts_map or {}
    used_titles       = set()
    messages          = []

    # ── Header message with news ──────────────────────────────────────────────
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

    # ── Individual game cards ─────────────────────────────────────────────────
    for g in games:
        home = g["home_team"]
        away = g["away_team"]

        pred         = match_prediction(g, predictions)
        home_streak  = streaks.get(home, {})
        away_streak  = streaks.get(away, {})
        home_notices = star_notices.get(home, [])
        away_notices = star_notices.get(away, [])
        home_b2b     = b2b_alerts_map.get(home, [])
        away_b2b     = b2b_alerts_map.get(away, [])

        # Check if either team is on a B2B
        home_rest = home_streak.get("rest_days")
        away_rest = away_streak.get("rest_days")
        is_b2b_game = home_rest == 0 or away_rest == 0

        # Travel factor — distance from each team's last game to tonight's host arena
        away_travel_miles = get_team_travel_miles(away_streak, away, home)
        home_travel_miles = get_team_travel_miles(home_streak, home, home)
        away_long_travel = (
            away_travel_miles is not None and away_travel_miles >= TRAVEL_DISTANCE_THRESHOLD
            and away_rest is not None and away_rest <= TRAVEL_REST_THRESHOLD
        )
        home_long_travel = (
            home_travel_miles is not None and home_travel_miles >= TRAVEL_DISTANCE_THRESHOLD
            and home_rest is not None and home_rest <= TRAVEL_REST_THRESHOLD
        )

        lines = [f"🏟 <b>{away} @ {home}</b>", f"🕐 {g['game_time']}"]
        lines.append("───────────────────")

        # Records — abbreviated
        rec = []
        if g["away_record"]: rec.append(f"{abbr(away)} {g['away_record']}")
        if g["home_record"]: rec.append(f"{abbr(home)} {g['home_record']}")
        if rec: lines.append("📋 " + " | ".join(rec))

        # All-time series
        h2h = get_h2h_record(home, away)
        if h2h:
            lines.append(h2h)

        # Streak + rest
        sp = []
        for team, streak in [(away, away_streak), (home, home_streak)]:
            s = format_streak(streak)
            r = format_rest(streak.get("rest_days"))
            if s or r:
                p = abbr(team)
                if s: p += f" ({s})"
                if r: p += f" · {r}"
                sp.append(p)
        if sp: lines.append("🔥 " + " | ".join(sp))

        # Injuries — last name only for cleaner display
        away_inj = injury_map.get(away, g.get("away_injuries", []))
        home_inj = injury_map.get(home, g.get("home_injuries", []))
        if away_inj:
            inj_names = ", ".join(i.split("(")[0].strip().split()[-1] + " (" + i.split("(")[1] for i in away_inj)
            lines.append(f"🚑 {abbr(away)}: {inj_names}")
        if home_inj:
            inj_names = ", ".join(i.split("(")[0].strip().split()[-1] + " (" + i.split("(")[1] for i in home_inj)
            lines.append(f"🚑 {abbr(home)}: {inj_names}")

        # B2B fatigue alerts
        for alert in (away_b2b + home_b2b):
            lines.append(alert)

        # Travel notes — long haul + short rest for either team
        if away_long_travel:
            lines.append(f"\u2708\ufe0f {abbr(away)} long travel \u2014 {int(away_travel_miles):,}mi on {format_rest(away_rest).lower()}")
        if home_long_travel:
            lines.append(f"\u2708\ufe0f {abbr(home)} long travel \u2014 {int(home_travel_miles):,}mi on {format_rest(home_rest).lower()}")

        # Minutes — ONLY on B2B games
        if is_b2b_game:
            home_avg_mins = avg_minutes_map.get(home, {})
            away_avg_mins = avg_minutes_map.get(away, {})
            all_mins = {}
            all_mins.update(away_avg_mins)
            all_mins.update(home_avg_mins)
            if all_mins:
                top_mins = sorted(all_mins.items(), key=lambda x: x[1], reverse=True)[:4]
                mins_str = " · ".join(f"{p.split()[-1]} {m}m" for p, m in top_mins)
                lines.append(f"⏱ B2B Min (L5): {mins_str}")

        # Streak notices
        for notice in (away_notices + home_notices)[:3]:
            lines.append(notice)

        # Prop picks
        game_props = prop_picks_map.get(home, []) + prop_picks_map.get(away, [])
        if game_props:
            lines.append("🎯 <b>Props</b>")
            for prop in game_props[:4]:
                stat_label = {"pts": "PTS", "reb": "REB", "ast": "AST", "stl": "STL", "blk": "BLK"}.get(prop["stat"], prop["stat"].upper())
                tier_emoji = "✅" if prop["confidence_tier"] == "green" else "⚠️"
                hr         = prop.get("hit_rate_overall")
                hr_str     = f"{hr}%" if hr else "?"
                lines.append(f"  {tier_emoji} {prop['player_name'].split()[-1]} o{prop['line']} {stat_label} — {hr_str}")

        # ── Model section ─────────────────────────────────────────────────────
        lines.append("───────────────────")
        if pred:
            away_prob = pred.get("away_prob", 50)
            home_prob = pred.get("home_prob", 50)
            winner    = pred.get("predicted_winner", "")
            w_prob    = pred.get("winner_prob", 50)
            game_key  = f"{away} @ {home}"

            # Line movement
            lm = line_movement_map.get(game_key, {})
            if lm:
                open_h  = lm.get("opening_home_ml")
                close_h = lm.get("closing_home_ml")
                open_a  = lm.get("opening_away_ml")
                close_a = lm.get("closing_away_ml")
                sharp   = lm.get("sharp_signal", "")
                if open_h and close_h:
                    lines.append(f"📉 {abbr(home)} {open_h:+d}→{close_h:+d} | {abbr(away)} {open_a:+d}→{close_a:+d}")
                if sharp:
                    lines.append(f"🔔 {sharp}")

            # ESPN divergence — only show if winner differs
            espn_game            = espn_probs.get(game_key, {})
            divergence_line      = ""
            divergence_downgrade = False
            if espn_game and ESPN_PROB_ENABLED:
                espn_home = espn_game.get("home_prob", 50)
                espn_away = espn_game.get("away_prob", 50)
                div = check_divergence(home_prob, espn_home)
                if div["diverged"]:
                    espn_winner  = home if espn_home > espn_away else away
                    model_winner = winner
                    if espn_winner != model_winner:
                        divergence_downgrade = True
                        divergence_line = (
                            f"⚠️ Divergence — Model: {abbr(model_winner)} | "
                            f"ESPN: {abbr(espn_winner)} (gap: {div['gap']} pts)"
                        )

            lines.append(f"📊 {abbr(away)} {away_prob}% · {abbr(home)} {home_prob}%")
            if divergence_line:
                lines.append(divergence_line)

            # Log to DB
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

            # Confidence tier — keyed off EDGE, not win probability.
            # Win probability only says who the model thinks wins the
            # game outright; edge says whether the price is actually
            # worth betting. A 51% underdog with a 30% edge is a
            # BETTER bet than a 74% favorite with a 5% edge, so the
            # color has to track edge, not w_prob. Thresholds below
            # are conservative placeholders (matched to the existing
            # has_edge>=8 bar elsewhere in this file) — see 2026-07-20
            # note in calibration-and-mlb-gap: 80-pick WNBA sample was
            # too small/noisy to tune exact cutoffs, revisit later.
            w_prob_val = pred.get("winner_prob", 0)
            edge_val   = pred.get("edge", 0)
            if edge_val >= 15:
                conf_tier  = "green"
                tier_emoji = "🟢"
            elif edge_val >= 8:
                conf_tier  = "yellow"
                tier_emoji = "🟡"
            else:
                conf_tier  = "red"
                tier_emoji = "🔴"

            # Unified Pick/Model line — same wording MLB's format_game_card
            # uses, shown regardless of whether this game clears the edge
            # bar, so the projected winner is always visible.
            odds_val = pred.get("odds")
            odds_fmt = f" ({'+' if odds_val > 0 else ''}{odds_val})" if odds_val is not None else ""
            if pred.get("has_edge") and pred.get("pick_label"):
                pick_team_headline = pred["pick_label"].replace(" ML", "").strip()
                lines.append(f"✅ <b>Pick: {pick_team_headline} ({w_prob_val}%)</b>{odds_fmt}")
            else:
                lines.append(f"🤖 Model: {winner} ({w_prob_val}%)")

            if pred.get("has_edge") and pred.get("pick_label"):
                pick_team = pred["pick_label"].replace(" ML", "").strip()
                odds_val  = pred.get("odds")
                odds_str  = f" | odds: {'+' if odds_val > 0 else ''}{odds_val}" if odds_val is not None else ""
                pick_injuries = injury_map.get(pick_team, g.get("home_injuries" if pick_team == home else "away_injuries", []))
                star_list = WNBA_STAR_PLAYERS.get(pick_team, [])
                star_out_count = sum(
                    1 for inj in pick_injuries
                    if ("(Out)" in inj or "(Doubtful)" in inj)
                    and any(star.lower() in inj.lower() for star in star_list)
                )
                if star_out_count >= 2:
                    lines.append(f"⚠️ Edge suppressed — {abbr(pick_team)} missing {star_out_count} key players")
                else:
                    pick_streak = streaks.get(pick_team, {})
                    pick_rest   = pick_streak.get("rest_days")

                    downgrade_reasons = []
                    if pick_rest == 0:
                        downgrade_reasons.append(f"{abbr(pick_team)} on B2B")
                    if divergence_downgrade:
                        downgrade_reasons.append("ESPN divergence")
                    if pick_team == away and away_long_travel:
                        downgrade_reasons.append(f"{abbr(pick_team)} long travel ({int(away_travel_miles):,}mi)")
                    if pick_team == home and home_long_travel:
                        downgrade_reasons.append(f"{abbr(pick_team)} long travel ({int(home_travel_miles):,}mi)")

                    if downgrade_reasons and conf_tier == "green":
                        conf_tier  = "yellow"
                        tier_emoji = "🟡"
                        lines.append(f"{tier_emoji} <b>Confidence: YELLOW</b> (+{pred.get('edge', 0)}% edge)")
                        lines.append(f"⚠️ Downgraded — {', '.join(downgrade_reasons)}")
                    else:
                        lines.append(f"{tier_emoji} <b>Confidence: {conf_tier.upper()}</b> (+{pred.get('edge', 0)}% edge)")
                        if downgrade_reasons:
                            lines.append(f"⚠️ Note — {', '.join(downgrade_reasons)}")

                    # Spread
                    spread_pick   = pred.get("spread_pick")
                    spread_prob   = pred.get("spread_cover_prob")
                    posted_spread = pred.get("posted_spread")
                    pred_margin   = pred.get("pred_margin")
                    if spread_pick and spread_prob and posted_spread is not None and pred_margin is not None and spread_prob >= 60:
                        lines.append(f"📐 Spread: {spread_pick} | {spread_prob}% cover")

                    # Totals
                    proj_total   = pred.get("projected_total")
                    posted_total = pred.get("posted_total")
                    over_prob    = pred.get("over_prob")
                    under_prob   = pred.get("under_prob")
                    if proj_total and posted_total:
                        total_edge = round(proj_total - posted_total, 1)
                        if abs(total_edge) >= 4 and abs(total_edge) <= 15:
                            direction  = "OVER" if total_edge > 0 else "UNDER"
                            total_prob = over_prob if total_edge > 0 else under_prob
                            lines.append(f"🎯 Total: {direction} {posted_total} | {total_prob}%")
            else:
                lines.append("🔴 No edge pick")
                proj_total   = pred.get("projected_total")
                posted_total = pred.get("posted_total")
                if proj_total and posted_total:
                    total_edge = round(proj_total - posted_total, 1)
                    if abs(total_edge) >= 4 and abs(total_edge) <= 15:
                        direction = "OVER" if total_edge > 0 else "UNDER"
                        lines.append(f"🎯 Lean: {direction} {posted_total} (model {proj_total})")

            # Projected score — shown whenever available, regardless of
            # edge status, matching MLB's format_game_card behavior.
            projected = pred.get("projected", "")
            if projected:
                lines.append(f"📐 Projected: {projected}")
        else:
            lines.append("📊 Model prediction unavailable")

        lines.append("")
        lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
        messages.append("\n".join(lines))

    return messages


def send_message(text: str):
    from discord_alerts import send_discord_message, html_to_discord_markdown
    ok = send_discord_message(html_to_discord_markdown(text), webhook_url=DISCORD_WEBHOOK_GAME_PICKS)
    if ok:
        print("Digest sent successfully.")
    else:
        print("Digest send failed — see error above.")


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

    print("Fetching star player streaks and B2B alerts...")
    star_notices    = {}
    avg_minutes_map = {}
    b2b_alerts_map  = {}
    for team_name, _ in all_teams:
        rest_days = streaks.get(team_name, {}).get("rest_days")
        notices, avg_mins, b2b_alerts = fetch_star_player_streaks(team_name, rest_days=rest_days)
        if notices:
            star_notices[team_name] = notices
            print(f"  {team_name}: {len(notices)} streak notice(s)")
        if avg_mins:
            avg_minutes_map[team_name] = avg_mins
        if b2b_alerts:
            b2b_alerts_map[team_name] = b2b_alerts
            print(f"  {team_name}: {len(b2b_alerts)} B2B alert(s)")

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

    # Prop picks
    prop_picks_map = {}
    try:
        from database import get_conn as _get_conn
        _conn  = _get_conn()
        _c     = _conn.cursor()
        _today = get_today_ct().strftime("%Y-%m-%d")
        _c.execute("""
            SELECT player_name, team_name, stat, line,
                   over_odds, under_odds, hit_rate_overall, confidence_tier
            FROM player_props
            WHERE date = ? AND sport = ? AND confidence_tier IN ('green', 'yellow')
            ORDER BY hit_rate_overall DESC
        """, (_today, "wnba"))
        all_props_today = [dict(r) for r in _c.fetchall()]
        _c.execute("""
            SELECT player_name, team_name FROM wnba_game_log
            WHERE team_name != '' GROUP BY player_name ORDER BY date DESC
        """)
        player_team_map = {r["player_name"]: r["team_name"] for r in _c.fetchall()}
        _conn.close()
        for prop in all_props_today:
            team = prop.get("team_name") or player_team_map.get(prop["player_name"], "")
            prop["team_name"] = team
            if team:
                prop_picks_map.setdefault(team, []).append(prop)
        if prop_picks_map:
            total = sum(len(v) for v in prop_picks_map.values())
            print(f"  Loaded {total} prop pick(s) for {len(prop_picks_map)} team(s)")
    except Exception as e:
        print(f"  Prop picks load error (non-fatal): {e}")

    # Line movement
    line_movement_map = {}
    try:
        from database import get_conn as _get_conn
        _conn = _get_conn()
        _c    = _conn.cursor()
        _today = get_today_ct().strftime("%Y-%m-%d")
        _c.execute("""
            SELECT home_team, away_team, opening_home_ml, opening_away_ml,
                   closing_home_ml, closing_away_ml, movement_home, movement_away, sharp_signal
            FROM line_movement WHERE date = ? AND sport = ?
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
        games, predictions, streaks, star_notices,
        avg_minutes_map=avg_minutes_map,
        b2b_alerts_map=b2b_alerts_map,
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