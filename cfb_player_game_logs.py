"""
cfb_player_game_logs.py — Culture & Pulse Analytics
Pulls CFB player stats from ESPN box scores.
Scrapes completed games and builds per-game logs into cfb_game_log,
same table/pattern star_players.py and the projections engine expect
(star_players.py's STAR_CONFIG["cfb"] already references cfb_game_log
with passing_attempts/rushing_attempts/receptions columns).

Directly mirrors nfl_player_game_logs.py — same ESPN box score shape
(stat CATEGORIES per team: passing/rushing/receiving, each with its own
keys/athletes array), same merge-by-player logic, same substring
key-hint matching instead of exact-index lookup. Only real differences:
ESPN sport path (football/college-football vs football/nfl) and a much
larger, non-static team list (FBS has 130+ teams vs NFL's fixed 32) —
reused directly from cfb_data.py's existing FBS_TEAM_IDS rather than
duplicated here.

IMPORTANT — unverified against a live payload, same caveat as NFL's
build: the 2026 CFB season hasn't started as of this build (games
start late August), so there's no way to confirm ESPN's real stat key
names for college football specifically match NFL's until a real
completed game exists to test against. CFB's box score COULD differ
from NFL's in category naming or structure even though both are ESPN
football products — don't assume identical just because the sport is
similar. Run debug_dump_keys() against a real completed 2025 CFB game
BEFORE trusting a real backfill — same five-minute check that caught
the NFL passing_attempts/completions overlap bug before it silently
saved wrong data all season.

Usage:
  python cfb_player_game_logs.py backfill        # pull completed 2025 season
  python cfb_player_game_logs.py update           # pull last 7 days
  python cfb_player_game_logs.py debug <event_id> # dump real stat keys from one game
"""

import requests
import time
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from database import get_conn

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

ESPN_SPORT_PATH = "football/college-football"

# 2025 CFB regular season opened the week of Aug 23, 2025 (Week 0 games
# start slightly earlier than most FBS teams' Week 1) — backfill runs
# through today. No 2026 season data yet.
CFB_SEASON_START = "20250823"

# Same hint structure as nfl_player_game_logs.py — unverified for CFB
# specifically until debug_dump_keys() confirms it against a real game,
# see module docstring.
STAT_KEY_HINTS = {
    "passing": {
        "passing_completions": "completion",   # combined "completions/passingAttempts" field — see NFL's note: no separate "attempt" hint, since that substring also matches this combined key and would overwrite the correct attempts value with the completions number
        "passing_yards":       "passingyards",
        "passing_tds":         "passingtouchdown",
        "interceptions":       "interception",
    },
    "rushing": {
        "rushing_attempts": "rushingattempt",
        "rushing_yards":    "rushingyards",
        "rushing_tds":      "rushingtouchdown",
    },
    "receiving": {
        "receptions":       "reception",
        "receiving_yards":  "receivingyards",
        "receiving_tds":    "receivingtouchdown",
        "targets":          "target",   # captured if present, not used for star volume — same as NFL
    },
}

GAME_LOG_COLUMNS = [
    "passing_completions", "passing_attempts", "passing_yards", "passing_tds", "interceptions",
    "rushing_attempts", "rushing_yards", "rushing_tds",
    "receptions", "receiving_yards", "receiving_tds", "targets",
]


def get_game_ids(date_str: str) -> list:
    """Get all completed CFB game IDs for a given date (YYYYMMDD).
    NOTE: FBS has 130+ teams and a much heavier Saturday slate than the
    NFL — a single date can return far more games than NFL's scoreboard
    call ever would, so backfill runs will naturally take longer."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{ESPN_SPORT_PATH}/scoreboard?dates={date_str}&limit=200"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        data = r.json()
        ids  = []
        for event in data.get("events", []):
            completed = event.get("status", {}).get("type", {}).get("completed", False)
            if completed:
                ids.append(event.get("id"))
        return ids
    except Exception as e:
        print(f"  Scoreboard error {date_str}: {e}")
        return []


def debug_dump_keys(event_id: str):
    """Prints every stat category's real keys for one game — run this
    against a real completed CFB game ID before trusting a backfill.
    Compare the printed keys against STAT_KEY_HINTS above and fix any
    mismatch. This is the check that would have caught it if CFB's
    category names differ from NFL's, before a real backfill ran."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{ESPN_SPORT_PATH}/summary?event={event_id}"
    r    = requests.get(url, headers=HEADERS, timeout=10)
    data = r.json()
    boxscore = data.get("boxscore", {})
    for team_data in boxscore.get("players", []):
        team_name = team_data.get("team", {}).get("displayName", "")
        print(f"\n=== {team_name} ===")
        for stat_group in team_data.get("statistics", []):
            print(f"  Category: {stat_group.get('name')}")
            print(f"    Keys: {stat_group.get('keys')}")
            athletes = stat_group.get("athletes", [])
            if athletes:
                sample = athletes[0]
                print(f"    Sample athlete: {sample.get('athlete', {}).get('displayName')} -> {sample.get('stats')}")


_warned_hints = set()


def _find_key_index(stat_keys: list, hint: str, category: str = ""):
    hint = hint.lower()
    for i, k in enumerate(stat_keys):
        if hint in k.lower():
            return i
    warn_key = (category, hint)
    if warn_key not in _warned_hints:
        _warned_hints.add(warn_key)
        print(f"  ⚠️  WARNING: could not map stat hint '{hint}' in category '{category}' — "
              f"real keys were {stat_keys}. This stat will save as 0 until STAT_KEY_HINTS is fixed.")
    return None


def _extract_stat(stat_keys: list, raw_stats: list, hint: str, category: str = ""):
    """Handles both plain numeric values and combined 'made-attempted'
    or 'made/attempted' fields. Returns (made_or_value, attempted_or_none)."""
    idx = _find_key_index(stat_keys, hint, category)
    if idx is None or idx >= len(raw_stats):
        return 0.0, None
    val = raw_stats[idx]
    val_str = str(val)
    for delim in ("/", "-"):
        if delim in val_str:
            parts = val_str.split(delim)
            if len(parts) == 2:
                try:
                    return float(parts[0]), float(parts[1])
                except ValueError:
                    pass
    try:
        return float(val), None
    except (ValueError, TypeError):
        return 0.0, None


def parse_box_score(event_id: str) -> list:
    """Pull box score from a completed game. Returns list of player stat
    dicts, one per player, merging all stat categories (passing/rushing/
    receiving) that player appeared in for this game."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{ESPN_SPORT_PATH}/summary?event={event_id}"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=10)
        data = r.json()
    except Exception as e:
        print(f"  Box score error {event_id}: {e}")
        return []

    boxscore = data.get("boxscore", {})
    players  = boxscore.get("players", [])
    if not players:
        return []

    team_names = [t.get("team", {}).get("displayName", "") for t in players]

    home_away_map = {}
    for comp in data.get("header", {}).get("competitions", []):
        for competitor in comp.get("competitors", []):
            tname = competitor.get("team", {}).get("displayName", "")
            home_away_map[tname] = competitor.get("homeAway", "")

    by_player = {}

    for team_data in players:
        team_name = team_data.get("team", {}).get("displayName", "")
        opponent  = next((t for t in team_names if t != team_name), "")

        for stat_group in team_data.get("statistics", []):
            category  = (stat_group.get("name") or "").lower()
            hints     = STAT_KEY_HINTS.get(category)
            if not hints:
                continue  # category we don't track (kicking, punting, defensive, etc. — Phase 1 scope)

            stat_keys = stat_group.get("keys", [])
            athletes  = stat_group.get("athletes", [])

            for athlete_data in athletes:
                athlete     = athlete_data.get("athlete", {})
                player_name = athlete.get("displayName", "")
                position    = athlete.get("position", {}).get("abbreviation", "")
                raw_stats   = athlete_data.get("stats", [])
                if not player_name or not raw_stats:
                    continue

                row = by_player.setdefault(player_name, {
                    "player_name": player_name, "team_name": team_name,
                    "position": position, "opponent": opponent,
                    "home_away": home_away_map.get(team_name, ""),
                    **{col: 0.0 for col in GAME_LOG_COLUMNS},
                })

                for col, hint in hints.items():
                    made, attempted = _extract_stat(stat_keys, raw_stats, hint, category)
                    if col == "passing_completions":
                        row["passing_completions"] = made
                        row["passing_attempts"] = attempted if attempted is not None else 0.0
                    else:
                        row[col] = made

    return list(by_player.values())


def save_game_stats(game_stats: list, date_str: str):
    """Save individual game stats to cfb_game_log.
    cfb_game_log already exists in schema_postgres.sql with matching
    columns — no inline CREATE TABLE, same pattern as every other sport
    stat file post-migration."""
    conn = get_conn()
    c    = conn.cursor()

    saved = 0
    for p in game_stats:
        try:
            c.execute("""
                INSERT INTO cfb_game_log
                (date, player_name, team_name, position,
                 passing_completions, passing_attempts, passing_yards, passing_tds, interceptions,
                 rushing_attempts, rushing_yards, rushing_tds,
                 receptions, receiving_yards, receiving_tds, targets,
                 opponent, home_away)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date, player_name, team_name) DO NOTHING
            """, (
                date_str, p["player_name"], p["team_name"], p.get("position", ""),
                p["passing_completions"], p["passing_attempts"], p["passing_yards"], p["passing_tds"], p["interceptions"],
                p["rushing_attempts"], p["rushing_yards"], p["rushing_tds"],
                p["receptions"], p["receiving_yards"], p["receiving_tds"], p["targets"],
                p.get("opponent", ""), p.get("home_away", ""),
            ))
            saved += 1
        except Exception as e:
            conn.rollback()
            print(f"  Save error {p['player_name']}: {e}")

    conn.commit()
    conn.close()
    return saved


def backfill_season(start_date: str = CFB_SEASON_START, end_date: str = None):
    """Pull all completed CFB games from start_date to end_date (defaults
    to today). Pass end_date for a limited test range before running the
    full season — e.g. one Saturday's slate to spot-check before
    trusting the rest. Given FBS's much larger team count, strongly
    recommend testing a single date range first (NFL's equivalent test
    was 2 weeks; CFB's Saturday-heavy schedule means even 1-2 dates is
    a meaningful test here)."""
    start_date = (start_date or CFB_SEASON_START).strip()
    end_date   = end_date.strip() if end_date else None

    start = datetime.strptime(start_date, "%Y%m%d")
    end   = datetime.strptime(end_date, "%Y%m%d") if end_date else datetime.now()
    total_games   = 0
    total_players = 0

    print(f"\nBackfilling CFB box scores from {start_date} to {end.strftime('%Y%m%d')}...")
    print("(2025 season is complete — this pulls historical data since no 2026 games exist yet)\n")

    current = start
    while current <= end:
        date_str = current.strftime("%Y%m%d")
        game_ids = get_game_ids(date_str)

        if game_ids:
            print(f"  {date_str}: {len(game_ids)} game(s)")
            for gid in game_ids:
                stats = parse_box_score(gid)
                if stats:
                    saved = save_game_stats(stats, date_str)
                    total_players += saved
                    total_games   += 1
                time.sleep(0.3)

        current += timedelta(days=1)

    print(f"\nBackfill complete: {total_games} games, {total_players} player-game records")


def update_recent(days: int = 7):
    """Pull last N days of games. No-op until the 2026 season starts."""
    today = datetime.now()
    total = 0

    print(f"\nUpdating CFB stats for last {days} days...")

    for i in range(days - 1, -1, -1):
        date     = today - timedelta(days=i)
        date_str = date.strftime("%Y%m%d")
        game_ids = get_game_ids(date_str)

        if game_ids:
            print(f"  {date_str}: {len(game_ids)} game(s)")
            for gid in game_ids:
                stats = parse_box_score(gid)
                if stats:
                    saved = save_game_stats(stats, date_str)
                    total += saved
                time.sleep(0.3)

    print(f"Update complete: {total} player-game records added")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "backfill":
            start_arg = sys.argv[2] if len(sys.argv) > 2 else CFB_SEASON_START
            end_arg   = sys.argv[3] if len(sys.argv) > 3 else None
            backfill_season(start_arg, end_arg)
        elif arg == "update":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            update_recent(days)
        elif arg == "debug" and len(sys.argv) > 2:
            debug_dump_keys(sys.argv[2])
        else:
            print("Usage: python cfb_player_game_logs.py [backfill|update|debug <event_id>]")
    else:
        print("Usage: python cfb_player_game_logs.py [backfill|update|debug <event_id>]")
