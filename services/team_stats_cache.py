"""
services/team_stats_cache.py
Persistent (Supabase-backed) cache for live ESPN team stats, shared by
nfl_data.py's get_team_stats() and cfb_data.py's get_profile(). Both
previously cached team stats in-process only (_stats_cache dicts),
which reset to empty on every fresh deploy — the next request after a
deploy had to live-fetch every team in that day's slate from ESPN
sequentially and uncached. That's exactly what caused /nfl/edges'
2026-09-11 incident: a deploy landed mid-run, wiped nfl_data.py's
_stats_cache, and the next /nfl/edges call took ~8 minutes fetching
all 32 teams live (see the 2026-09-08 audit comment in nfl_data.py
for the same failure mode observed earlier).

Same pattern as services/odds_parser.py's odds_api_cache: stored in
the shared DB via database.get_conn() (the one thing that actually
persists across ephemeral deploys/processes), keyed by (sport,
team_name), with a TTL checked in Python — not SQL — so it works
identically across Postgres/Turso/SQLite.

TEAM_STATS_CACHE_TTL_SECONDS is much longer than the odds cache's
2 hours: a team's per-game stats only change when that team finishes
a new game — once a week for NFL, a few times a week for CFB — not
the fast-moving numbers odds are. 6 hours comfortably survives
same-day redeploys and retries while still picking up post-game stat
updates well before that team's next start.
"""
import time
import json
from typing import Optional

TEAM_STATS_CACHE_TTL_SECONDS = 6 * 3600


def read_team_stats_cache(sport: str, team_name: str) -> Optional[dict]:
    """Returns the cached stats dict for (sport, team_name) if a row
    exists and is within TEAM_STATS_CACHE_TTL_SECONDS, else None (miss,
    expired, or any read error — a cache problem degrades to a real
    ESPN fetch rather than breaking the request)."""
    try:
        from database import get_conn
        conn = get_conn()
        c = conn.cursor()
        c.execute(
            "SELECT stats_json, cached_at FROM team_stats_cache WHERE sport = ? AND team_name = ?",
            (sport, team_name),
        )
        row = c.fetchone()
        conn.close()
        if not row:
            return None
        if time.time() - row["cached_at"] >= TEAM_STATS_CACHE_TTL_SECONDS:
            return None
        return json.loads(row["stats_json"])
    except Exception as e:
        print(f"  Team stats cache read error ({sport}/{team_name}): {e}")
        return None


def write_team_stats_cache(sport: str, team_name: str, stats_dict: dict):
    """Best-effort — a failed cache write must never block returning
    real data to the caller, so this only ever prints on error.
    Callers should NOT write fabricated/default stats here (e.g. a
    last-resort flat-default fallback when ESPN gave nothing at all) —
    that would poison the cache with fake numbers for a full TTL
    window even if ESPN recovers seconds later. Only persist real or
    real-prior-season data."""
    try:
        from database import get_conn
        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO team_stats_cache (sport, team_name, cached_at, stats_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (sport, team_name) DO UPDATE SET
                cached_at  = EXCLUDED.cached_at,
                stats_json = EXCLUDED.stats_json
        """, (sport, team_name, int(time.time()), json.dumps(stats_dict)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  Team stats cache write error ({sport}/{team_name}): {e}")
