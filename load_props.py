"""
load_props.py — Culture & Pulse Analytics
==========================================
Two responsibilities in this file:

1. load_props() — the READ function dashboard.py imports and calls
   (Tab 2: Player Props). Queries player_props LEFT JOIN prop_results
   from Turso via database.get_conn(), same pattern as load_picks() in
   dashboard.py. Handles schema drift (older rows/deploys missing the
   projection_* columns) via PRAGMA table_info instead of assuming.

2. Everything below run() — MANUAL FALLBACK ONLY as of 2026-07-01. The
   daily flow is now automated:
     fetch_prizepicks_props.py (10 AM CT cron) -> wnba_props_alert.py (10:15 AM CT cron)
   Use this only if PropLine's API is down, rate-limited (1,000 req/day
   free tier), or missing a specific line you need. It has its own
   simpler confidence-tier logic (no off-role downgrade, no PRA/PR/PA/RA
   support — see STAT_KEY_MAP below) and writes to the same player_props
   row as the automated pipeline, so whichever one runs LAST wins for
   that player/stat. This part writes to a local cp_analytics.db
   (sqlite3), NOT Turso — separate from load_props() above.

Usage:
    py load_props.py     # manual fallback only — fill out props_today.txt first
"""

import os
import sqlite3
import requests
import pandas as pd
from database import get_conn
from datetime import datetime, timezone, timedelta

# =============================================================================
# READ — used by dashboard.py (Turso)
# =============================================================================

def load_props() -> pd.DataFrame:
    """Player Props tab data source. Same PRAGMA table_info pattern as
    load_picks() in dashboard.py: projection columns (projected_stat,
    projection_edge_pct, etc.) only exist once fetch_prizepicks_props.py
    has saved at least one projection, so check what's really there
    instead of assuming — keeps this from crashing on a fresh deploy or
    an old row."""
    conn = get_conn()

    existing_cols = set()
    try:
        cur = conn.execute("PRAGMA table_info(player_props)")
        existing_cols = {row[1] for row in cur.fetchall()}
    except Exception:
        pass

    has_opponent_team = "opponent_team" in existing_cols
    projection_cols = ["projected_stat", "projection_edge", "projection_edge_pct",
                        "projection_direction", "projection_tier", "defense_factor"]
    available_proj_cols = [c for c in projection_cols if c in existing_cols]

    opponent_expr = "COALESCE(pp.opponent_team, pp.opponent)" if has_opponent_team else "pp.opponent"
    proj_select = ", ".join(f"pp.{c}" for c in available_proj_cols)
    proj_select_bare = ", ".join(available_proj_cols)

    cols = (["date", "sport", "player_name", "team_name", "opponent", "stat", "line",
             "over_odds", "under_odds", "hit_rate_overall", "confidence_tier"]
            + available_proj_cols
            + ["actual_value", "hit", "team_won"])

    query_with_results = f"""
        SELECT pp.date, pp.sport, pp.player_name, pp.team_name,
               {opponent_expr} as opponent,
               pp.stat, pp.line, pp.over_odds, pp.under_odds,
               pp.hit_rate_overall, pp.confidence_tier
               {"," + proj_select if proj_select else ""},
               pr.actual_value, pr.hit, pr.team_won
        FROM player_props pp
        LEFT JOIN (
            SELECT pr1.*
            FROM prop_results pr1
            WHERE pr1.rowid = (
                SELECT pr2.rowid
                FROM prop_results pr2
                WHERE pr2.date = pr1.date
                  AND pr2.player_name = pr1.player_name
                  AND pr2.stat = pr1.stat
                ORDER BY pr2.scored_at DESC, pr2.rowid DESC
                LIMIT 1
            )
        ) pr
          ON pr.date = pp.date AND pr.player_name = pp.player_name AND pr.stat = pp.stat
        ORDER BY pp.date DESC
    """
    # prop_results only gets created once prop_tracker.py runs for the first
    # time — until then, fall back to player_props alone so props still show
    # as PENDING instead of crashing the whole dashboard.
    try:
        cur = conn.execute(query_with_results)
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    except Exception:
        base_cols = ["date", "sport", "player_name", "team_name", "opponent", "stat", "line",
                     "over_odds", "under_odds", "hit_rate_overall", "confidence_tier"] + available_proj_cols
        query_no_results = f"""
            SELECT date, sport, player_name, team_name,
                   {opponent_expr.replace("pp.", "")} as opponent,
                   stat, line, over_odds, under_odds, hit_rate_overall, confidence_tier
                   {"," + proj_select_bare if proj_select_bare else ""}
            FROM player_props
            ORDER BY date DESC
        """
        cur = conn.execute(query_no_results)
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=base_cols)
        df["actual_value"] = None
        df["hit"] = None
        df["team_won"] = None
        # ensure every column the rest of the app expects is present, even
        # if this deploy's table doesn't have the projection columns yet
        for c in projection_cols:
            if c not in df.columns:
                df[c] = None
        return df


# =============================================================================
# MANUAL FALLBACK ONLY — writes to local cp_analytics.db (sqlite3), separate
# from load_props() above which reads from Turso. Run directly via CLI only.
# =============================================================================

DB_PATH         = os.path.join(os.path.dirname(__file__), "cp_analytics.db")
PROPS_FILE      = os.path.join(os.path.dirname(__file__), "props_today.txt")
CENTRAL_OFFSET  = -5
LOOKBACK_GAMES  = 10  # games to calculate hit rate from
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}
ESPN_WNBA_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"
ESPN_WNBA_SUMMARY    = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary"

STAT_KEY_MAP = {
    "pts": "points",
    "reb": "rebounds",
    "ast": "assists",
    "stl": "steals",
    "blk": "blocks",
}

# ── WNBA team roster map (player → team) ─────────────────────────────────────
WNBA_PLAYER_TEAMS = {
    "Rhyne Howard": "Atlanta Dream", "Angel Reese": "Atlanta Dream",
    "Allisha Gray": "Atlanta Dream", "Te-Hina Paopao": "Atlanta Dream",
    "Jordin Canada": "Atlanta Dream", "Isobel Borlase": "Atlanta Dream",
    "Kamilla Cardoso": "Chicago Sky", "Skylar Diggins": "Chicago Sky",
    "Natasha Cloud": "Chicago Sky", "Rachel Banham": "Chicago Sky",
    "DiJonai Carrington": "Chicago Sky", "Aicha Coulibaly": "Chicago Sky",
    "Brittney Griner": "Connecticut Sun", "Leila Lacan": "Connecticut Sun",
    "Aaliyah Edwards": "Connecticut Sun", "Nell Angloma": "Connecticut Sun",
    "Raegan Beers": "Connecticut Sun", "Kennedy Burke": "Connecticut Sun",
    "Arike Ogunbowale": "Dallas Wings", "Paige Bueckers": "Dallas Wings",
    "Azzi Fudd": "Dallas Wings", "Alysha Clark": "Dallas Wings",
    "Aziaha James": "Dallas Wings", "Haley Jones": "Dallas Wings",
    "Tiffany Hayes": "Golden State Valkyries", "Kayla Thornton": "Golden State Valkyries",
    "Veronica Burton": "Golden State Valkyries", "Laeticia Amihere": "Golden State Valkyries",
    "Kaila Charles": "Golden State Valkyries", "Kaitlyn Chen": "Golden State Valkyries",
    "Caitlin Clark": "Indiana Fever", "Aliyah Boston": "Indiana Fever",
    "Kelsey Mitchell": "Indiana Fever", "Monique Billings": "Indiana Fever",
    "Sophie Cunningham": "Indiana Fever", "Damiris Dantas": "Indiana Fever",
    "A'ja Wilson": "Las Vegas Aces", "Jackie Young": "Las Vegas Aces",
    "Chennedy Carter": "Las Vegas Aces", "Janiah Barker": "Las Vegas Aces",
    "Kierstan Bell": "Las Vegas Aces", "Dana Evans": "Las Vegas Aces",
    "Dearica Hamby": "Los Angeles Sparks", "Kelsey Plum": "Los Angeles Sparks",
    "Nneka Ogwumike": "Los Angeles Sparks", "Kate Martin": "Los Angeles Sparks",
    "Ariel Atkins": "Los Angeles Sparks", "Cameron Brink": "Los Angeles Sparks",
    "Napheesa Collier": "Minnesota Lynx", "Kayla McBride": "Minnesota Lynx",
    "Olivia Miles": "Minnesota Lynx", "Maya Caldwell": "Minnesota Lynx",
    "Emma Cechova": "Minnesota Lynx", "Nia Coffey": "Minnesota Lynx",
    "Breanna Stewart": "New York Liberty", "Sabrina Ionescu": "New York Liberty",
    "Jonquel Jones": "New York Liberty", "Satou Sabally": "New York Liberty",
    "Rebecca Allen": "New York Liberty", "Pauline Astier": "New York Liberty",
    "Alyssa Thomas": "Phoenix Mercury", "DeWanna Bonner": "Phoenix Mercury",
    "Kahleah Copper": "Phoenix Mercury", "Natasha Mack": "Phoenix Mercury",
    "Monique Akoa Makani": "Phoenix Mercury", "Valeriane Ayayi": "Phoenix Mercury",
    "Carla Leite": "Portland Fire", "Bridget Carleton": "Portland Fire",
    "Sarah Ashlee Barker": "Portland Fire", "Frieda Buhner": "Portland Fire",
    "Emily Engstler": "Portland Fire", "Sania Feagin": "Portland Fire",
    "Zia Cooke": "Seattle Storm", "Stefanie Dolson": "Seattle Storm",
    "Awa Fam": "Seattle Storm", "Natisha Hiedeman": "Seattle Storm",
    "Mackenzie Holmes": "Seattle Storm", "Jordan Horston": "Seattle Storm",
    "Marina Mabrey": "Toronto Tempo", "Kiki Rice": "Toronto Tempo",
    "Julie Allemand": "Toronto Tempo", "Maria Conde": "Toronto Tempo",
    "Temi Fagbenle": "Toronto Tempo", "Isabelle Harrison": "Toronto Tempo",
    "Shakira Austin": "Washington Mystics", "Lauren Betts": "Washington Mystics",
    "Rori Harmon": "Washington Mystics", "Georgia Amoore": "Washington Mystics",
    "Sonia Citron": "Washington Mystics", "Angela Dugalic": "Washington Mystics",
}


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def parse_props_file():
    props = []
    if not os.path.exists(PROPS_FILE):
        print(f"ERROR: {PROPS_FILE} not found.")
        return props
    with open(PROPS_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                print(f"  Skipping malformed line: {line}")
                continue
            player_name = parts[0]
            stat        = parts[1].lower()
            try:
                prop_line = float(parts[2])
            except ValueError:
                print(f"  Skipping bad line value: {line}")
                continue
            over_odds  = int(parts[3]) if len(parts) > 3 and parts[3] else None
            under_odds = int(parts[4]) if len(parts) > 4 and parts[4] else None
            if stat not in STAT_KEY_MAP:
                print(f"  Unknown stat '{stat}' for {player_name} — skipping")
                continue
            props.append({
                "player_name": player_name,
                "stat":        stat,
                "line":        prop_line,
                "over_odds":   over_odds,
                "under_odds":  under_odds,
            })
    return props


def fetch_recent_game_ids(team_name: str, n: int = LOOKBACK_GAMES) -> list:
    today    = get_today_ct()
    game_ids = []
    for days_back in range(1, 45):
        check_date = (today - timedelta(days=days_back)).strftime("%Y%m%d")
        url = f"{ESPN_WNBA_SCOREBOARD}?dates={check_date}"
        try:
            r    = requests.get(url, headers=HEADERS, timeout=8)
            data = r.json()
            for event in data.get("events", []):
                completed   = event.get("status", {}).get("type", {}).get("completed", False)
                comps       = event.get("competitions", [{}])
                competitors = comps[0].get("competitors", []) if comps else []
                team_names  = [c.get("team", {}).get("displayName", "") for c in competitors]
                if completed and team_name in team_names:
                    game_ids.append({
                        "id":       event.get("id"),
                        "date":     str(today - timedelta(days=days_back)),
                        "opponent": next((t for t in team_names if t != team_name), ""),
                        "home_away": "home" if competitors and
                            next((c for c in competitors if c.get("team", {}).get("displayName") == team_name), {}).get("homeAway") == "home"
                            else "away",
                    })
        except:
            pass
        if len(game_ids) >= n:
            break
    return game_ids[:n]


def fetch_player_stat_from_game(game_id: str, player_name: str, team_name: str, stat: str) -> float | None:
    espn_key = STAT_KEY_MAP.get(stat)
    if not espn_key:
        return None
    url = f"{ESPN_WNBA_SUMMARY}?event={game_id}"
    try:
        r        = requests.get(url, headers=HEADERS, timeout=10)
        data     = r.json()
        boxscore = data.get("boxscore", {})
        for team_data in boxscore.get("players", []):
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
                if p_name.lower() != player_name.lower():
                    continue
                raw = ath.get("stats", [])
                if not raw:
                    return None
                try:
                    idx = stat_keys.index(espn_key)
                    val = raw[idx]
                    return float(val) if val not in ("N/A", "-", "", None) else None
                except (ValueError, IndexError):
                    return None
    except Exception as e:
        print(f"    Box score error ({game_id}): {e}")
    return None


def calculate_hit_rates(player_name: str, team_name: str, stat: str, line: float, game_logs: list) -> dict:
    """
    game_logs: list of {id, date, opponent, home_away, stat_value}
    Returns hit rates overall, vs today's opponent, home/away, b2b.
    """
    overall     = [g for g in game_logs if g.get("stat_value") is not None]
    hits        = [g for g in overall if g["stat_value"] > line]
    hit_rate    = round(len(hits) / len(overall) * 100, 1) if overall else None

    return {
        "hit_rate_overall": hit_rate,
        "games_overall":    len(overall),
        "hit_rate_vs_opp":  None,   # populated later when opponent is known
        "hit_rate_home_away": None, # populated later
        "hit_rate_b2b":     None,   # populated later
        "games_vs_opp":     0,
        "games_home_away":  0,
    }


def get_confidence_tier(hit_rate: float | None) -> str:
    if hit_rate is None:
        return "red"
    if hit_rate >= 70:
        return "green"
    if hit_rate >= 55:
        return "yellow"
    return "red"


def get_today_opponent(team_name: str) -> tuple:
    """Returns (opponent_name, home_away) for today's game."""
    today = get_today_ct().strftime("%Y%m%d")
    url   = f"{ESPN_WNBA_SCOREBOARD}?dates={today}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=8)
        data = r.json()
        for event in data.get("events", []):
            comps       = event.get("competitions", [{}])
            competitors = comps[0].get("competitors", []) if comps else []
            team_names  = [c.get("team", {}).get("displayName", "") for c in competitors]
            if team_name in team_names:
                opponent  = next((t for t in team_names if t != team_name), "")
                home_away = next(
                    (c.get("homeAway") for c in competitors
                     if c.get("team", {}).get("displayName") == team_name), "away"
                )
                return opponent, home_away
    except Exception as e:
        print(f"  Could not fetch today's opponent for {team_name}: {e}")
    return "", "away"


def insert_prop(conn, prop_data: dict):
    sql = """
        INSERT INTO player_props (
            date, sport, player_name, team_name, opponent, home_away,
            stat, line, over_odds, under_odds,
            hit_rate_overall, hit_rate_vs_opp, hit_rate_home_away, hit_rate_b2b,
            games_overall, games_vs_opp, games_home_away,
            confidence_tier, source, captured_at
        ) VALUES (
            :date, :sport, :player_name, :team_name, :opponent, :home_away,
            :stat, :line, :over_odds, :under_odds,
            :hit_rate_overall, :hit_rate_vs_opp, :hit_rate_home_away, :hit_rate_b2b,
            :games_overall, :games_vs_opp, :games_home_away,
            :confidence_tier, :source, :captured_at
        )
        ON CONFLICT(date, player_name, stat) DO UPDATE SET
            team_name         = excluded.team_name,
            opponent          = excluded.opponent,
            home_away         = excluded.home_away,
            line              = excluded.line,
            over_odds         = excluded.over_odds,
            under_odds        = excluded.under_odds,
            hit_rate_overall  = excluded.hit_rate_overall,
            hit_rate_vs_opp   = excluded.hit_rate_vs_opp,
            hit_rate_home_away= excluded.hit_rate_home_away,
            hit_rate_b2b      = excluded.hit_rate_b2b,
            games_overall     = excluded.games_overall,
            confidence_tier   = excluded.confidence_tier,
            source            = excluded.source,
            captured_at       = excluded.captured_at
    """
    conn.execute(sql, prop_data)
    conn.commit()


def run():
    today = get_today_ct()
    print(f"Loading props for {today}...\n")

    props = parse_props_file()
    if not props:
        print("No props found in props_today.txt. Exiting.")
        return

    print(f"Found {len(props)} prop(s) in props_today.txt\n")
    conn = sqlite3.connect(DB_PATH)

    for prop in props:
        player  = prop["player_name"]
        stat    = prop["stat"]
        line    = prop["line"]
        team    = WNBA_PLAYER_TEAMS.get(player, "")

        print(f"Processing: {player} o{line} {stat.upper()}")

        if not team:
            print(f"  WARNING: No team found for {player} — skipping\n")
            continue

        # Get today's opponent and home/away
        opponent, home_away = get_today_opponent(team)
        print(f"  Team: {team} | Opponent: {opponent or 'unknown'} | {home_away}")

        # Fetch recent game IDs
        print(f"  Fetching last {LOOKBACK_GAMES} games...")
        game_logs_raw = fetch_recent_game_ids(team, LOOKBACK_GAMES)

        # Fetch stat value per game
        game_logs = []
        for g in game_logs_raw:
            val = fetch_player_stat_from_game(g["id"], player, team, stat)
            game_logs.append({**g, "stat_value": val})
            result = f"{val}" if val is not None else "DNP/missing"
            print(f"    {g['date']} vs {g['opponent']}: {result}")

        # Calculate hit rates
        rates = calculate_hit_rates(player, team, stat, line, game_logs)

        # Situational: vs today's opponent
        if opponent:
            vs_opp = [g for g in game_logs if g["opponent"] == opponent and g.get("stat_value") is not None]
            if vs_opp:
                hits = [g for g in vs_opp if g["stat_value"] > line]
                rates["hit_rate_vs_opp"] = round(len(hits) / len(vs_opp) * 100, 1)
                rates["games_vs_opp"]    = len(vs_opp)

        # Situational: home/away split
        ha_games = [g for g in game_logs if g["home_away"] == home_away and g.get("stat_value") is not None]
        if ha_games:
            hits = [g for g in ha_games if g["stat_value"] > line]
            rates["hit_rate_home_away"] = round(len(hits) / len(ha_games) * 100, 1)
            rates["games_home_away"]    = len(ha_games)

        tier = get_confidence_tier(rates["hit_rate_overall"])
        print(f"  Hit rate (L{rates['games_overall']}): {rates['hit_rate_overall']}% | Tier: {tier}")

        prop_data = {
            "date":               str(today),
            "sport":              "wnba",
            "player_name":        player,
            "team_name":          team,
            "opponent":           opponent,
            "home_away":          home_away,
            "stat":               stat,
            "line":               line,
            "over_odds":          prop["over_odds"],
            "under_odds":         prop["under_odds"],
            "hit_rate_overall":   rates["hit_rate_overall"],
            "hit_rate_vs_opp":    rates.get("hit_rate_vs_opp"),
            "hit_rate_home_away": rates.get("hit_rate_home_away"),
            "hit_rate_b2b":       None,
            "games_overall":      rates["games_overall"],
            "games_vs_opp":       rates.get("games_vs_opp", 0),
            "games_home_away":    rates.get("games_home_away", 0),
            "confidence_tier":    tier,
            "source":             "manual",
            "captured_at":        datetime.now(timezone.utc).isoformat(),
        }

        insert_prop(conn, prop_data)
        print(f"  Saved to DB.\n")

    conn.close()
    print(f"Done. {len(props)} prop(s) loaded for {today}.")
    print("Run your digest now — props will appear in the alert automatically.")


if __name__ == "__main__":
    run()