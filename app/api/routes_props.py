from fastapi import APIRouter, Query
import sys
import os
from datetime import datetime, timedelta

_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if _root not in sys.path:
    sys.path.insert(0, _root)

router = APIRouter(prefix="/props", tags=["Props"])


def _today_ct() -> str:
    # Matches the Central-time "today" convention used by fetch_prizepicks_props.py
    return (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d")


@router.get("/browser")
def props_browser(sport: str = Query(default=None), date: str = Query(default=None)):
    """
    Returns every player_props row for a given date (default: today),
    optionally filtered by sport. This is the data source for the
    dashboard's Props Browser tab.
    """
    from database import get_conn

    target_date = date or _today_ct()

    conn = get_conn()
    c = conn.cursor()
    query = "SELECT * FROM player_props WHERE date = ?"
    params = [target_date]
    if sport:
        query += " AND sport = ?"
        params.append(sport)
    c.execute(query, params)
    rows = [dict(r) for r in c.fetchall()]
    conn.close()

    props = []
    for r in rows:
        props.append({
            "player":       r.get("player_name"),
            "team":         r.get("team_name"),
            "sport":        r.get("sport"),
            "stat":         r.get("stat"),
            "line":         r.get("line"),
            "over_odds":    r.get("over_odds"),
            "under_odds":   r.get("under_odds"),
            "hit_rate":     r.get("hit_rate_overall"),
            "hit_rate_games": r.get("games_overall"),
            "projected":    r.get("projected_stat"),
            "edge":         r.get("projection_edge"),
            "edge_pct":     r.get("projection_edge_pct"),
            "direction":    r.get("projection_direction"),
            "tier":         r.get("projection_tier") or r.get("confidence_tier"),
            "opponent":     r.get("opponent_team") or r.get("opponent"),
            "defense_factor": r.get("defense_factor"),
        })

    props.sort(key=lambda x: abs(x.get("edge_pct") or 0), reverse=True)
    return {"date": target_date, "sport": sport, "count": len(props), "props": props}
