"""
draft_update.py - Culture & Pulse Analytics
Run after NBA or WNBA draft night to refresh rosters.
Pulls new rosters, adds rookies, updates team assignments.

Usage:
  python draft_update.py wnba    # refresh WNBA rosters
  python draft_update.py nba     # refresh NBA rosters
  python draft_update.py all     # refresh both
"""

import requests
import time
from datetime import datetime
from database import get_conn
from player_profiles import (
    init_player_tables,
    calculate_impact_score,
    WNBA_TEAM_IDS,
    NBA_TEAM_IDS,
    fetch_roster,
    parse_player,
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept":     "application/json",
}

CURRENT_YEAR = datetime.now().year


def update_rosters(sport: str):
    """
    Refresh all rosters for a sport.
    - Adds new players (rookies, free agent signings)
    - Updates team assignments (trades)
    - Marks departed players as inactive
    - Preserves historical stats
    """
    init_player_tables()

    team_ids = WNBA_TEAM_IDS if sport == "wnba" else NBA_TEAM_IDS
    season   = str(CURRENT_YEAR) if sport == "wnba" else f"{CURRENT_YEAR-1}-{str(CURRENT_YEAR)[2:]}"

    conn  = get_conn()
    c     = conn.cursor()

    print(f"\nUpdating {sport.upper()} rosters ({season})...")
    print(f"{'─'*50}")

    # Get current roster from DB
    c.execute("""
        SELECT player_name, team_name FROM player_profiles
        WHERE sport = ? AND season = ?
    """, (sport, season))
    existing = {row["player_name"]: row["team_name"] for row in c.fetchall()}
    print(f"  Players in DB: {len(existing)}")

    new_players     = 0
    updated_players = 0
    total_players   = 0

    for team_name, team_id in team_ids.items():
        athletes = fetch_roster(sport, team_name, team_id)

        if not athletes:
            print(f"  No roster: {team_name}")
            continue

        for athlete in athletes:
            player = parse_player(athlete, team_name, sport, season)

            if not player["player_name"]:
                continue

            total_players += 1
            is_new     = player["player_name"] not in existing
            team_changed = (
                player["player_name"] in existing and
                existing[player["player_name"]] != team_name
            )

            if is_new:
                new_players += 1
                print(f"  NEW: {player['player_name']} → {team_name}")
            elif team_changed:
                updated_players += 1
                old_team = existing[player["player_name"]]
                print(f"  TRADE: {player['player_name']} {old_team} → {team_name}")

            try:
                c.execute("""
                    INSERT INTO player_profiles
                    (sport, team_name, player_name, position, height, weight,
                     college, draft_year, draft_round, draft_pick, jersey_number,
                     status, pts_per_game, reb_per_game, ast_per_game,
                     stl_per_game, blk_per_game, fg_pct, three_pct, ft_pct,
                     minutes_per_game, usage_rate, impact_score, season)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (sport, team_name, player_name, season) DO UPDATE SET
                        position          = EXCLUDED.position,
                        height            = EXCLUDED.height,
                        weight            = EXCLUDED.weight,
                        college           = EXCLUDED.college,
                        draft_year        = EXCLUDED.draft_year,
                        draft_round       = EXCLUDED.draft_round,
                        draft_pick        = EXCLUDED.draft_pick,
                        jersey_number     = EXCLUDED.jersey_number,
                        status            = EXCLUDED.status,
                        pts_per_game      = EXCLUDED.pts_per_game,
                        reb_per_game      = EXCLUDED.reb_per_game,
                        ast_per_game      = EXCLUDED.ast_per_game,
                        stl_per_game      = EXCLUDED.stl_per_game,
                        blk_per_game      = EXCLUDED.blk_per_game,
                        fg_pct            = EXCLUDED.fg_pct,
                        three_pct         = EXCLUDED.three_pct,
                        ft_pct            = EXCLUDED.ft_pct,
                        minutes_per_game  = EXCLUDED.minutes_per_game,
                        usage_rate        = EXCLUDED.usage_rate,
                        impact_score      = EXCLUDED.impact_score
                """, (
                    player["sport"], player["team_name"], player["player_name"],
                    player["position"], player["height"], player["weight"],
                    player["college"], player["draft_year"], player["draft_round"],
                    player["draft_pick"], player["jersey_number"], "active",
                    player["pts_per_game"], player["reb_per_game"], player["ast_per_game"],
                    player["stl_per_game"], player["blk_per_game"], player["fg_pct"],
                    player["three_pct"], player["ft_pct"], player["minutes_per_game"],
                    player["usage_rate"], player["impact_score"], player["season"],
                ))
            except Exception as e:
                conn.rollback()
                print(f"  Save error {player['player_name']}: {e}")

        time.sleep(0.3)

    # Mark players no longer on any roster as inactive
    c.execute("""
        SELECT player_name FROM player_profiles
        WHERE sport = ? AND season = ? AND status = 'active'
    """, (sport, season))
    db_players = {row["player_name"] for row in c.fetchall()}

    # Get current ESPN players
    current_players = set()
    for team_name, team_id in team_ids.items():
        athletes = fetch_roster(sport, team_name, team_id)
        for a in athletes:
            name = a.get("displayName") or a.get("fullName", "")
            if name:
                current_players.add(name)
        time.sleep(0.2)

    departed = db_players - current_players
    if departed:
        print(f"\n  Players no longer on roster:")
        for player_name in departed:
            print(f"  INACTIVE: {player_name}")
            c.execute("""
                UPDATE player_profiles
                SET status = 'inactive'
                WHERE sport = ? AND player_name = ? AND season = ?
            """, (sport, player_name, season))

    conn.commit()
    conn.close()

    print(f"\n{'─'*50}")
    print(f"  Roster update complete:")
    print(f"  Total players:   {total_players}")
    print(f"  New players:     {new_players}")
    print(f"  Trades/moves:    {updated_players}")
    print(f"  Departed:        {len(departed)}")
    print(f"{'─'*50}")


def update_nba_stats_post_draft():
    """
    Pull updated NBA stats after draft.
    Rookies will have 0 stats initially.
    """
    print("\nRefreshing NBA player stats...")
    from player_stats_backfill import backfill_nba_stats
    backfill_nba_stats()


def update_wnba_stats_post_draft():
    """
    Rebuild WNBA player averages from box scores after draft.
    """
    print("\nRefreshing WNBA player stats...")
    from wnba_player_stats import update_recent
    update_recent(days=30)


def run_full_draft_update(sport: str):
    """Run complete post-draft update for a sport."""
    print(f"\n{'='*50}")
    print(f"  POST-DRAFT UPDATE — {sport.upper()}")
    print(f"  {datetime.now().strftime('%B %d, %Y')}")
    print(f"{'='*50}")

    update_rosters(sport)

    if sport == "wnba":
        update_wnba_stats_post_draft()
    elif sport == "nba":
        update_nba_stats_post_draft()

    print(f"\n{sport.upper()} draft update complete.")
    print(f"Run 'python player_profiles.py top {sport}' to see updated rankings.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "wnba":
            run_full_draft_update("wnba")
        elif arg == "nba":
            run_full_draft_update("nba")
        elif arg == "all":
            run_full_draft_update("wnba")
            run_full_draft_update("nba")
        elif arg == "rosters":
            sport = sys.argv[2].lower() if len(sys.argv) > 2 else "wnba"
            update_rosters(sport)
    else:
        print("Usage: python draft_update.py [wnba|nba|all|rosters]")
        print("")
        print("  wnba     — full post-draft update for WNBA")
        print("  nba      — full post-draft update for NBA")
        print("  all      — update both leagues")
        print("  rosters  — roster update only (no stats refresh)")