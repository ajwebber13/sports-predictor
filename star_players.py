"""
star_players.py — Culture & Pulse Analytics
=============================================
Auto-selects the top N "star" players per team per sport, based on
season volume stats already sitting in each sport's game log table.

No hardcoded name lists to maintain — as a player's role changes
(more/less playing time), the star list updates itself on the next run.

Sport config: table = game log table, volume_col = the stat that best
proxies "gets real playing time" (minutes for WNBA, at_bats for MLB),
min_games = games needed before a player counts (avoids one-game flukes).

Add a new sport by adding one line to STAR_CONFIG below, once that
sport has a game log table with a player_name/team_name/date + a
volume column.

NOTE on volume_col: this string is interpolated directly into
AVG({volume_col}) in the query below — it's not limited to a bare
column name. NFL/CFB use this to pass a full SQL expression (a
touches proxy combining several columns) since football has no
single cross-position volume stat the way minutes/at_bats works
for basketball/baseball.
"""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn as _get_conn

STAR_CONFIG = {
    "wnba": {"table": "wnba_game_log", "volume_col": "minutes", "min_games": 5, "spans_calendar_years": False},
    "mlb":  {"table": "mlb_game_log",  "volume_col": "at_bats", "min_games": 5, "spans_calendar_years": False},
    "nba":  {"table": "nba_game_log",  "volume_col": "minutes", "min_games": 5, "spans_calendar_years": True},
    # NFL/CFB: no single cross-position volume stat like minutes/at_bats —
    # a QB's attempts and a WR's receptions aren't the same unit. Use a
    # combined "touches" proxy instead: passing attempts + rush attempts +
    # receptions. Deliberately excludes targets — ESPN box score reliability
    # for targets wasn't confirmed as of this build; receptions is the stat
    # we're sure is there. volume_col here is a raw SQL expression, not just
    # a column name (see module docstring above).
    # min_games is lower than WNBA/MLB (5) because NFL is a 17-game season
    # and CFB ~12-13 — waiting for 5 games burns a quarter of the schedule.
    "nfl":  {"table": "nfl_game_log", "volume_col": "(COALESCE(passing_attempts,0) + COALESCE(rushing_attempts,0) + COALESCE(receptions,0))", "min_games": 3, "spans_calendar_years": False},
    "cfb":  {"table": "cfb_game_log", "volume_col": "(COALESCE(passing_attempts,0) + COALESCE(rushing_attempts,0) + COALESCE(receptions,0))", "min_games": 3, "spans_calendar_years": False},
}

_cache = {}  # {(sport, top_n, season): {team_name: [player_name, ...]}}


def get_star_players(sport: str, top_n: int = 3, season: str = "2026", use_cache: bool = True) -> dict:
    """
    Returns {team_name: [player_name, player_name, ...]} — the top_n
    players by season volume stat, per team, for the given sport.

    Returns {} for sports not in STAR_CONFIG (nothing to filter against
    yet — caller should fall back to unfiltered behavior and flag it).
    """
    cfg = STAR_CONFIG.get(sport)
    if not cfg:
        return {}

    cache_key = (sport, top_n, season)
    if use_cache and cache_key in _cache:
        return _cache[cache_key]

    table       = cfg["table"]
    volume_col  = cfg["volume_col"]
    min_games   = cfg["min_games"]
    spans_years = cfg.get("spans_calendar_years", False)

    # NBA (Oct-June) spans two calendar years — a "2026%" prefix would
    # silently drop every Oct-Dec 2025 game. Sports that span years use
    # the whole table (it holds one season until the next backfill),
    # everyone else filters by the season-year prefix as before.
    date_filter = "1=1"
    params = []
    if not spans_years:
        date_filter = "date LIKE ?"
        params.append(f"{season}%")

    conn = _get_conn()
    c = conn.cursor()
    try:
        c.execute(f"""
            SELECT player_name, team_name,
                   COUNT(*) as games,
                   AVG({volume_col}) as avg_volume
            FROM {table}
            WHERE {date_filter}
            GROUP BY player_name, team_name
            HAVING games >= ?
            ORDER BY team_name, avg_volume DESC
        """, (*params, min_games))
        rows = [dict(r) for r in c.fetchall()]
    except Exception as e:
        print(f"  ⚠️  star_players: couldn't read {table} for '{sport}' ({e}) — treating as unconfigured")
        conn.close()
        return {}
    conn.close()

    by_team = {}
    for r in rows:
        team = r["team_name"]
        by_team.setdefault(team, [])
        if len(by_team[team]) < top_n:
            by_team[team].append(r["player_name"])

    _cache[cache_key] = by_team
    return by_team


def is_star_player(sport: str, player_name: str, team_name: str = None, top_n: int = 3, season: str = "2026") -> bool:
    """
    True if player_name is in the top_n star list for their team.
    If team_name is unknown, checks across every team's star list
    (still correct, just slightly slower).
    """
    stars = get_star_players(sport, top_n=top_n, season=season)
    if not stars:
        # Sport not wired for star filtering yet — don't silently drop everyone.
        return True

    if team_name:
        return player_name in stars.get(team_name, [])

    return any(player_name in roster for roster in stars.values())


def filter_to_stars(sport: str, props: list, top_n: int = 3, season: str = "2026") -> tuple:
    """
    Splits a props list into (kept, dropped) based on the star list.
    props: list of dicts each with at least "player_name"; "team" or
    "home_team"/"away_team" used to resolve team_name when present.

    If the sport has no star config yet, everything is kept — caller's
    responsibility to note that filtering wasn't actually applied.
    """
    stars = get_star_players(sport, top_n=top_n, season=season)
    if not stars:
        return props, []

    all_star_names = set()
    for roster in stars.values():
        all_star_names.update(roster)

    kept, dropped = [], []
    for p in props:
        if p.get("player_name") in all_star_names:
            kept.append(p)
        else:
            dropped.append(p)

    return kept, dropped


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Show the current star player list for a sport")
    parser.add_argument("--sport", required=True)
    parser.add_argument("--top-n", type=int, default=3)
    parser.add_argument("--season", default="2026")
    args = parser.parse_args()

    stars = get_star_players(args.sport, top_n=args.top_n, season=args.season)
    if not stars:
        print(f"No star config for '{args.sport}' yet — needs a game log table wired into STAR_CONFIG.")
    else:
        for team, players in sorted(stars.items()):
            print(f"{team}: {', '.join(players)}")
