"""
fetch_prizepicks_props.py — Culture & Pulse Analytics
======================================================
Pulls today's WNBA/NBA/MLB/NFL player prop lines from PropLine API (free
tier, 1,000 requests/day, no credit card). Enriches each prop with hit
rates from prop_hit_rates.py and saves to the player_props table.

PropLine is drop-in compatible with The Odds API format.
Sign up for a free key at: https://prop-line.com

Usage:
    python fetch_prizepicks_props.py              # fetch WNBA + save to DB
    python fetch_prizepicks_props.py --dry-run    # print without saving
    python fetch_prizepicks_props.py --sport nba  # different sport
    python fetch_prizepicks_props.py --sport mlb  # baseball props
    python fetch_prizepicks_props.py --sport nfl  # football props
"""

import os
import sys
import time
import argparse
import requests
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_PATH = os.path.join(os.path.dirname(__file__), "cp_analytics.db")

PROPLINE_BASE  = "https://api.prop-line.com/v1"
PROPLINE_KEY   = os.getenv("PROPLINE_API_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}

SPORT_KEYS = {
    "wnba": "basketball_wnba",
    "nba":  "basketball_nba",
    "mlb":  "baseball_mlb",
    "nfl":  "football_nfl",
}

# PropLine market keys -> our stat key. Sport-specific market subsets are
# sent to PropLine per sport since basketball/baseball/football markets
# are mutually exclusive. MLB only includes the 4 verified stats
# prop_hit_rates.py can actually calculate. NFL market key names match
# The Odds API's standard NFL player-prop markets (PropLine's docstring
# claims drop-in compatibility) — UNVERIFIED against a real PropLine
# response, confirm with --dry-run against real odds before trusting a
# live save.
MARKET_MAP = {
    # Basketball (WNBA/NBA)
    "player_points":                   "pts",
    "player_rebounds":                 "reb",
    "player_assists":                  "ast",
    "player_steals":                   "stl",
    "player_blocks":                   "blk",
    "player_points_rebounds_assists":  "pra",
    "player_points_rebounds":          "pr",
    "player_points_assists":           "pa",
    "player_rebounds_assists":         "ra",
    # Baseball (MLB)
    "batter_hits":                     "hits",
    "batter_rbis":                     "rbis",
    "batter_runs_scored":              "runs",
    "batter_home_runs":                "hr",
    # Football (NFL)
    "player_pass_yds":                 "passing_yards",
    "player_pass_tds":                 "passing_tds",
    "player_pass_completions":         "passing_completions",
    "player_pass_attempts":            "passing_attempts",
    "player_pass_interceptions":       "interceptions",
    "player_rush_yds":                 "rushing_yards",
    "player_rush_attempts":            "rushing_attempts",
    "player_receptions":               "receptions",
    "player_reception_yds":            "receiving_yards",
    "player_reception_tds":            "receiving_tds",
}

SPORT_MARKETS = {
    "wnba": "player_points,player_rebounds,player_assists,player_steals,player_blocks,"
            "player_points_rebounds_assists,player_points_rebounds,player_points_assists,player_rebounds_assists",
    "nba":  "player_points,player_rebounds,player_assists,player_steals,player_blocks,"
            "player_points_rebounds_assists,player_points_rebounds,player_points_assists,player_rebounds_assists",
    "mlb":  "batter_hits,batter_rbis,batter_runs_scored,batter_home_runs",
    "nfl":  "player_pass_yds,player_pass_tds,player_pass_completions,player_pass_attempts,"
            "player_pass_interceptions,player_rush_yds,player_rush_attempts,"
            "player_receptions,player_reception_yds,player_reception_tds",
}

def get_today_ct() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=-5)).strftime("%Y-%m-%d")


def propline_get(path: str, params: dict = None):
    if not PROPLINE_KEY:
        print("  ❌ PROPLINE_API_KEY not set. Get a free key at https://prop-line.com")
        return None
    params = params or {}
    params["apiKey"] = PROPLINE_KEY
    try:
        r = requests.get(f"{PROPLINE_BASE}{path}", headers=HEADERS, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        print(f"  ❌ PropLine API error: {e}")
        return None
    except Exception as e:
        print(f"  ❌ Request failed: {e}")
        return None


def fetch_props_for_sport(sport: str, target_date: str = None) -> list:
    """
    Returns a flat list of prop dicts:
    { player_name, team, opponent, home_away, stat, line, over_odds, under_odds,
      home_team, away_team }
    home_team/away_team are the two teams in THIS game — used later to group
    the Telegram alert by matchup.
    """
    sport_key = SPORT_KEYS.get(sport)
    if not sport_key:
        print(f"  ❌ Unknown sport: {sport}")
        return []

    markets = SPORT_MARKETS.get(sport, "")
    if not markets:
        print(f"  ❌ No market map configured for sport: {sport}")
        return []

    events = propline_get(f"/sports/{sport_key}/events")
    if not events:
        return []

    today_ct = target_date or get_today_ct()

    def event_date_ct(commence_time: str) -> str:
        try:
            utc_dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
            ct_dt  = utc_dt + timedelta(hours=-5)
            return ct_dt.strftime("%Y-%m-%d")
        except Exception:
            return ""

    today_events = [
        e for e in events
        if event_date_ct(e.get("commence_time", "")) == today_ct
    ]

    if not today_events:
        print(f"  No {sport.upper()} events today ({today_ct})")
        return []

    print(f"  Found {len(today_events)} {sport.upper()} event(s) today")

    all_props = []

    for event in today_events:
        event_id  = event["id"]
        home_team = event.get("home_team", "")
        away_team = event.get("away_team", "")

        data = propline_get(f"/sports/{sport_key}/events/{event_id}/odds", {"markets": markets})
        if not data:
            continue

        time.sleep(0.3)

        for bookmaker in data.get("bookmakers", []):
            bm_key = bookmaker.get("key", "")
            if bm_key not in ("draftkings", "fanduel", "bovada"):
                continue

            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")
                stat       = MARKET_MAP.get(market_key)
                if not stat:
                    continue

                player_outcomes = {}
                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description", "").strip()
                    if not player_name:
                        continue
                    direction = outcome.get("name", "")
                    price     = outcome.get("price")
                    line      = outcome.get("point")
                    if player_name not in player_outcomes:
                        player_outcomes[player_name] = {"line": line, "over_odds": None, "under_odds": None}
                    if direction == "Over":
                        player_outcomes[player_name]["over_odds"] = price
                        player_outcomes[player_name]["line"]      = line
                    elif direction == "Under":
                        player_outcomes[player_name]["under_odds"] = price

                for player_name, prop_data in player_outcomes.items():
                    line = prop_data.get("line")
                    if not line:
                        continue

                    import re
                    clean_name = re.sub(r'\s*\([A-Z]{2,4}\)\s*$', '', player_name).strip()

                    all_props.append({
                        "player_name": clean_name,
                        "team":        "",
                        "home_team":   home_team,
                        "away_team":   away_team,
                        "stat":        stat,
                        "line":        float(line),
                        "over_odds":   prop_data.get("over_odds"),
                        "under_odds":  prop_data.get("under_odds"),
                        "bookmaker":   bm_key,
                    })

            if bm_key == "draftkings":
                break

    seen    = {}
    deduped = []
    for p in all_props:
        key = (p["player_name"], p["stat"], p["line"])
        if key not in seen:
            seen[key] = True
            deduped.append(p)

    return deduped


def run(sport: str = "wnba", dry_run: bool = False, top_n: int = 3, all_players: bool = False):
    from prop_hit_rates import get_hit_rate, setup_props_table, save_prop_with_hit_rates
    from star_players import get_star_players, filter_to_stars

    today = get_today_ct()
    setup_props_table()

    print(f"\n{'='*55}")
    print(f"  PropLine Props — {sport.upper()} — {today}")
    print(f"  {'DRY RUN' if dry_run else 'LIVE WRITE'}")
    print(f"{'='*55}\n")

    if not PROPLINE_KEY:
        print("  ❌ Set PROPLINE_API_KEY env var first.")
        print("  Get a free key (no credit card) at: https://prop-line.com\n")
        return

    props = fetch_props_for_sport(sport)
    print(f"\n  Parsed {len(props)} props\n")

    if not props:
        print("  No props returned.\n")
        return

    star_config_exists = bool(get_star_players(sport, top_n=top_n))

    if all_players:
        print(f"  --all-players set: skipping star filter, using full board ({len(props)} props)\n")
    elif not star_config_exists:
        print(f"  ⚠️  No star-player config for '{sport}' yet (needs a game log table) — "
              f"using full board ({len(props)} props). Filtering not applied.\n")
    else:
        props, dropped = filter_to_stars(sport, props, top_n=top_n)
        print(f"  Star filter: kept {len(props)} props (top {top_n}/team), "
              f"dropped {len(dropped)} bench/role-player props\n")

    if not props:
        print("  Nothing left after filtering.\n")
        return

    saved = 0
    for prop in props:
        player     = prop["player_name"]
        stat       = prop["stat"]
        line       = prop["line"]
        over_odds  = prop.get("over_odds")
        under_odds = prop.get("under_odds")

        data    = get_hit_rate(player, stat, line, sport=sport)
        overall = data.get("overall", {})
        hr      = overall.get("hit_rate")
        games   = overall.get("games", 0)
        tier    = data.get("confidence_tier", "insufficient")

        tier_emoji = {"green": "✅", "yellow": "⚠️", "red": "❌", "insufficient": "❓"}.get(tier, "")
        odds_str   = f"o{over_odds}/u{under_odds}" if over_odds and under_odds else ""

        print(f"  {player} o{line} {stat} {odds_str} — ", end="")
        if hr is not None:
            print(f"{hr}% ({games}G) {tier_emoji}")
        else:
            print(f"insufficient data ({games}G) ❓")

        projection = None
        player_team = None
        if sport == "wnba":
            from wnba_projections import project_prop, get_player_team
            player_team = get_player_team(player)
            home_team   = prop.get("home_team", "")
            away_team   = prop.get("away_team", "")
            opponent_team = None
            if player_team == home_team:
                opponent_team = away_team
            elif player_team == away_team:
                opponent_team = home_team

            projection = project_prop(player, stat, line, opponent_team=opponent_team)
            if projection.get("error"):
                print(f"      projection: insufficient recent data")
            else:
                df = projection["defense_factor"]
                df_str = f" | vs {opponent_team} D-factor {df}" if opponent_team else " | opponent unknown, no D adj"
                print(f"      projection: {projection['projected_minutes']} min x "
                      f"{projection['per_min_rate']}/min = {projection['projected_stat']} "
                      f"({projection['direction']} {projection['edge_pct']}%){df_str} "
                      f"{ {'green': '✅', 'yellow': '⚠️', 'red': '❌'}.get(projection['confidence_tier'], '') }")
        elif sport == "mlb":
            from mlb_projections import project_prop, get_player_team
            player_team = get_player_team(player)
            home_team   = prop.get("home_team", "")
            away_team   = prop.get("away_team", "")
            opponent_team = None
            if player_team == home_team:
                opponent_team = away_team
            elif player_team == away_team:
                opponent_team = home_team

            projection = project_prop(player, stat, line, opponent_team=opponent_team)
            if projection.get("error"):
                print(f"      projection: insufficient recent data")
            else:
                df = projection["defense_factor"]
                df_str = f" | vs {opponent_team} D-factor {df}" if opponent_team else " | opponent unknown, no D adj"
                print(f"      projection: {projection['projected_at_bats']} AB x "
                      f"{projection['per_ab_rate']}/AB = {projection['projected_stat']} "
                      f"({projection['direction']} {projection['edge_pct']}%){df_str} "
                      f"{ {'green': '✅', 'yellow': '⚠️', 'red': '❌'}.get(projection['confidence_tier'], '') }")
        elif sport == "nba":
            from nba_projections import project_prop, get_player_team
            player_team = get_player_team(player)
            home_team   = prop.get("home_team", "")
            away_team   = prop.get("away_team", "")
            opponent_team = None
            if player_team == home_team:
                opponent_team = away_team
            elif player_team == away_team:
                opponent_team = home_team

            projection = project_prop(player, stat, line, opponent_team=opponent_team)
            if projection.get("error"):
                print(f"      projection: insufficient recent data")
            else:
                df = projection["defense_factor"]
                df_str = f" | vs {opponent_team} D-factor {df}" if opponent_team else " | opponent unknown, no D adj"
                print(f"      projection: {projection['projected_minutes']} min x "
                      f"{projection['per_min_rate']}/min = {projection['projected_stat']} "
                      f"({projection['direction']} {projection['edge_pct']}%){df_str} "
                      f"{ {'green': '✅', 'yellow': '⚠️', 'red': '❌'}.get(projection['confidence_tier'], '') }")
        elif sport == "nfl":
            from nfl_projections import project_prop, get_player_team
            player_team = get_player_team(player)
            home_team   = prop.get("home_team", "")
            away_team   = prop.get("away_team", "")
            opponent_team = None
            if player_team == home_team:
                opponent_team = away_team
            elif player_team == away_team:
                opponent_team = home_team

            # NFL's volume driver differs by stat (pass attempts / rush
            # attempts / targets — see nfl_projections.py's STAT_CONFIG),
            # not one universal stat like WNBA/NBA's minutes, so this
            # print uses the generic volume_stat/projected_volume/
            # per_unit_rate field names instead of the basketball-specific
            # ones the other branches use.
            projection = project_prop(player, stat, line, opponent_team=opponent_team)
            if projection.get("error"):
                print(f"      projection: insufficient recent data")
            else:
                df = projection["defense_factor"]
                df_str = f" | vs {opponent_team} D-factor {df}" if opponent_team else " | opponent unknown, no D adj"
                print(f"      projection: {projection['projected_volume']} {projection['volume_stat']} x "
                      f"{projection['per_unit_rate']}/unit = {projection['projected_stat']} "
                      f"({projection['direction']} {projection['edge_pct']}%){df_str} "
                      f"{ {'green': '✅', 'yellow': '⚠️', 'red': '❌'}.get(projection['confidence_tier'], '') }")

        if not dry_run:
            save_prop_with_hit_rates(
                date        = today,
                player_name = player,
                team_name   = player_team or prop.get("team", ""),
                opponent    = opponent_team or "",
                home_away   = prop.get("home_away", ""),
                stat        = stat,
                line        = line,
                over_odds   = over_odds,
                under_odds  = under_odds,
                game_home_team = prop.get("home_team", ""),
                game_away_team = prop.get("away_team", ""),
                sport       = sport,
            )
            if sport == "wnba" and projection:
                from wnba_projections import save_projection
                save_projection(today, sport, player, stat, projection)
            elif sport == "mlb" and projection:
                from mlb_projections import save_projection
                save_projection(today, sport, player, stat, projection)
            elif sport == "nba" and projection:
                from nba_projections import save_projection
                save_projection(today, sport, player, stat, projection)
            elif sport == "nfl" and projection:
                from nfl_projections import save_projection
                save_projection(today, sport, player, stat, projection)
            saved += 1

    print(f"\n{'='*55}")
    if dry_run:
        print(f"  {len(props)} props previewed. Run without --dry-run to save.")
    else:
        print(f"  {saved} props saved to player_props table.")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport",   default="wnba")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top-n",   type=int, default=3, help="Star players per team to keep (default 3)")
    parser.add_argument("--all-players", action="store_true", help="Skip star filter, use full board")
    args = parser.parse_args()
    run(sport=args.sport, dry_run=args.dry_run, top_n=args.top_n, all_players=args.all_players)