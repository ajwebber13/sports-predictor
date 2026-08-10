"""
debug_injury_adj.py — one-off diagnostic for the WNBA injury_adj bug.

Prints, for every team with a live injury report:
  - each player's status, position, base_impact (position*severity only)
  - the player_profiles override value (if any) and which one "won"
  - the team's final total_impact and the resulting injury_adj_pts

Run:
  python debug_injury_adj.py wnba

Paste the full output back — this pinpoints whether the DTD/Probable
noise or the player_profiles scale mismatch (or both) is driving the
-5.81 avg adjustment.
"""

import sys
from intel_feed import (
    fetch_injuries,
    get_team_injury_impact,
    injury_adj_pts,
    POSITION_IMPACT_BY_SPORT,
    INJURY_SEVERITY,
)

def main():
    league = sys.argv[1].upper() if len(sys.argv) > 1 else "WNBA"
    injuries = fetch_injuries(league)

    if not injuries:
        print("No injury data returned — check ESPN endpoint / league name.")
        return

    pos_map = POSITION_IMPACT_BY_SPORT.get(league, POSITION_IMPACT_BY_SPORT["NBA"])

    grand_total = 0.0
    team_count = 0

    for team, reports in sorted(injuries.items()):
        print(f"\n{'='*70}")
        print(f"{team}")
        print(f"{'-'*70}")

        for r in reports:
            pos_weight = pos_map.get(r.position.upper(), pos_map.get("", 0.5))
            sev_weight = INJURY_SEVERITY.get(r.status, 0.3)
            base_impact = round(pos_weight * sev_weight, 3)

            print(f"  {r.player:25s} pos={r.position or '(none)':5s} "
                  f"status={r.status:15s} "
                  f"pos_w={pos_weight:.2f} sev_w={sev_weight:.2f} "
                  f"base_impact={base_impact:.3f}  "
                  f"FINAL impact={r.impact:.3f}"
                  f"{'  <-- OVERRIDE INFLATED' if r.impact > base_impact + 0.001 else ''}")

        total_impact, top3 = get_team_injury_impact(team, injuries)
        adj = injury_adj_pts(total_impact, league)
        print(f"\n  TOP-3 USED: {[i.player for i in top3]}")
        print(f"  team total_impact = {total_impact:.3f}  ->  injury_adj = {adj:+.2f} pts")

        grand_total += adj
        team_count += 1

    if team_count:
        print(f"\n{'='*70}")
        print(f"Teams with injury data: {team_count}")
        print(f"Average injury_adj across those teams: {grand_total / team_count:+.2f} pts")

if __name__ == "__main__":
    main()
