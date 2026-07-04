"""
fetch_prizepicks_props.py — Culture & Pulse Analytics
======================================================
Pulls today's WNBA (and NBA) player prop lines from PropLine API (free tier,
1,000 requests/day, no credit card). Enriches each prop with hit rates from
prop_hit_rates.py and saves to the player_props table.

PropLine is drop-in compatible with The Odds API format.
Sign up for a free key at: https://prop-line.com

Usage:
    python fetch_prizepicks_props.py              # fetch WNBA + save to DB
    python fetch_prizepicks_props.py --dry-run    # print without saving
    python fetch_prizepicks_props.py --sport nba  # different sport
"""

import os
import sys
import time
import argparse
import requests
from datetime import datetime, timezone, timedelta

# Load .env file if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DB_PATH = os.path.join(os.path.dirname(__file__), "cp_analytics.db")

PROPLINE_BASE  = "https://api.prop-line.com/v1"
PROPLINE_KEY   = os.getenv("PROPLINE_API_KEY", "")

SPORT_KEYS = {
    "wnba": "basketball_wnba",
    "nba":  "basketball_nba",
}

# PropLine market keys → our stat key
MARKET_MAP = {
    "player_points":                   "pts",
    "player_rebounds":                 "reb",
    "player_assists":                  "ast",
    "player_steals":                   "stl",
    "player_blocks":                   "blk",
    "player_points_rebounds_assists":  "pra",
    "player_points_rebounds":          "pr",
    "player_points_assists":           "pa",
    "player_rebounds_assists":         "ra",
}

MARKETS = ",".join(MARKET_MAP.keys())

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept":     "application/json",
}


def get_today_ct() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=-5)).strftime("%Y-%m-%d")


def propline_get(path: str, params: dict = None) -> dict | list | None:
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
    { player_name, team, opponent, home_away, stat, line, over_odds, under_odds }
    """
    sport_key = SPORT_KEYS.get(sport)
    if not sport_key:
        print(f"  ❌ Unknown sport: {sport}")
        return []

    # Step 1 — get today's events
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

        # Step 2 — get props per event
        data = propline_get(f"/sports/{sport_key}/events/{event_id}/odds", {"markets": MARKETS})
        if not data:
            continue

        time.sleep(0.3)  # be polite to the API

        for bookmaker in data.get("bookmakers", []):
            # Use DraftKings as primary source, fall back to first available
            bm_key = bookmaker.get("key", "")
            if bm_key not in ("draftkings", "fanduel", "bovada"):
                continue

            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")
                stat       = MARKET_MAP.get(market_key)
                if not stat:
                    continue

                # Group outcomes by player (Over/Under pairs)
                player_outcomes = {}
                for outcome in market.get("outcomes", []):
                    player_name = outcome.get("description", "").strip()
                    if not player_name:
                        continue
                    direction = outcome.get("name", "")  # Over or Under
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

                    # Strip team abbreviation e.g. "Kamilla Cardoso (CHI)" -> "Kamilla Cardoso"
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

            # Only use one bookmaker per event (DraftKings first)
            if bm_key == "draftkings":
                break

    # Deduplicate — keep best odds per player/stat/line
    seen    = {}
    deduped = []
    for p in all_props:
        key = (p["player_name"], p["stat"], p["line"])
        if key not in seen:
            seen[key] = True
            deduped.append(p)

    return deduped


def run(sport: str = "wnba", dry_run: bool = False):
    from prop_hit_rates import get_hit_rate, setup_props_table, save_prop_with_hit_rates

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

    saved = 0
    for prop in props:
        player    = prop["player_name"]
        stat      = prop["stat"]
        line      = prop["line"]
        over_odds = prop.get("over_odds")
        under_odds = prop.get("under_odds")

        # Get hit rate from our game log
        data    = get_hit_rate(player, stat, line)
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

        if not dry_run:
            save_prop_with_hit_rates(
                date        = today,
                player_name = player,
                team_name   = prop.get("team", ""),
                opponent    = "",
                home_away   = prop.get("home_away", ""),
                stat        = stat,
                line        = line,
                over_odds   = over_odds,
                under_odds  = under_odds,
            )
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
    args = parser.parse_args()
    run(sport=args.sport, dry_run=args.dry_run)