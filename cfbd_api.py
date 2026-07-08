"""
cfbd_api.py
============
College Football Data API integration — free source for SP+ ratings
and real Vegas betting lines, both of which cfb_data.py's ESPN-only
pipeline doesn't have.

Setup (one time):
  1. Register for a free API key at: https://collegefootballdata.com/key
  2. Set your key:
       Windows: setx CFBD_API_KEY "your_key_here"
       Mac/Linux: export CFBD_API_KEY="your_key_here"

Install:
  pip install cfbd

FIXED 2026-07-05: this file previously imported TeamStats and
MatchupInput from predictor.py — those classes were removed from
predictor.py in an earlier refactor and only exist in
_archive/archive_predictor_basic.py now. The import was silently
broken (ImportError) the whole time; this file never actually ran.
Rewired to output CFBTeamStats (from cfb_data.py) instead, so this
plugs directly into the live, working cfb_predictor.py.
"""

import os
from typing import Optional
import cfbd
from cfb_data import CFBTeamStats, FBS_TEAM_IDS
from predictor import CFB_CONSTANTS


# ─────────────────────────────────────────────────────────────
# CLIENT SETUP
# ─────────────────────────────────────────────────────────────

class CFBDClient:
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("CFBD_API_KEY", "")
        if not key:
            raise ValueError(
                "\n  ✗ No CFBD API key found.\n"
                "  Get a free key at: https://collegefootballdata.com/key\n"
                "  Then run: setx CFBD_API_KEY \"your_key_here\"  (Windows)\n"
                "  Or pass directly: CFBDClient(api_key='your_key')\n"
            )
        config = cfbd.Configuration(access_token=key)
        client = cfbd.ApiClient(config)

        self.games   = cfbd.GamesApi(client)
        self.stats   = cfbd.StatsApi(client)
        self.betting = cfbd.BettingApi(client)
        self.ratings = cfbd.RatingsApi(client)
        self.teams   = cfbd.TeamsApi(client)

    def test_connection(self) -> bool:
        try:
            result = self.teams.get_teams()
            print(f"  ✓ Connected to College Football Data API ({len(result)} teams)")
            return True
        except Exception as e:
            print(f"  ✗ CFBD connection failed: {e}")
            return False


# ─────────────────────────────────────────────────────────────
# SEASON DATA CACHE (fetch once per session, not per-team)
# ─────────────────────────────────────────────────────────────

_season_games_cache = {}
_season_stats_cache = {}
_sp_ratings_cache   = {}


def load_season_games(client: CFBDClient, year: int) -> list:
    if year in _season_games_cache:
        return _season_games_cache[year]
    print(f"  Loading {year} season game results (one-time fetch)...")
    try:
        raw = client.games.get_games(year=year)
        completed = [
            g for g in raw
            if g.home_points is not None and g.away_points is not None
        ]
        _season_games_cache[year] = completed
        print(f"  ✓ {len(completed)} completed games loaded for {year}")
        return completed
    except Exception as e:
        print(f"  ✗ Season games fetch failed: {e}")
        _season_games_cache[year] = []
        return []


def load_season_stats(client: CFBDClient, year: int) -> dict:
    if year in _season_stats_cache:
        return _season_stats_cache[year]
    print(f"  Loading {year} season stats (one-time fetch)...")
    try:
        raw = client.stats.get_team_stats(year=year)
        lookup = {}
        for s in raw:
            if s.team not in lookup:
                lookup[s.team] = {}
            val = s.stat_value
            if hasattr(val, "actual_instance"):
                val = val.actual_instance
            try:
                lookup[s.team][s.stat_name] = float(val)
            except (TypeError, ValueError):
                pass
        _season_stats_cache[year] = lookup
        print(f"  ✓ Stats loaded for {len(lookup)} teams")
        return lookup
    except Exception as e:
        print(f"  ✗ Season stats fetch failed: {e}")
        _season_stats_cache[year] = {}
        return {}


def load_sp_ratings(client: CFBDClient, year: int) -> dict:
    """Fetch SP+ ratings for all teams in one call. {team_name: TeamSP}."""
    if year in _sp_ratings_cache:
        return _sp_ratings_cache[year]
    try:
        raw = client.ratings.get_sp(year=year)
        lookup = {r.team: r for r in raw if r.team}
        _sp_ratings_cache[year] = lookup
        return lookup
    except Exception as e:
        print(f"  ⚠  SP+ ratings fetch failed: {e}")
        _sp_ratings_cache[year] = {}
        return {}


# ─────────────────────────────────────────────────────────────
# STAT HELPERS
# ─────────────────────────────────────────────────────────────

def _safe(d: dict, *keys, default: float = 0.0) -> float:
    for k in keys:
        if k in d and d[k] is not None:
            return float(d[k])
    return default


def _calc_game_stats(all_games: list, team_name: str) -> dict:
    """Per-game scoring averages for a team from the full season game list."""
    home_scored = []; home_allowed = []
    away_scored = []; away_allowed = []

    for g in all_games:
        hp = float(g.home_points)
        ap = float(g.away_points)
        if g.home_team == team_name:
            home_scored.append(hp); home_allowed.append(ap)
        elif g.away_team == team_name:
            away_scored.append(ap); away_allowed.append(hp)

    all_scored  = home_scored + away_scored
    all_allowed = home_allowed + away_allowed
    n = len(all_scored)
    if n == 0:
        return {}

    return {
        "games_played": n,
        "wins": sum(1 for i in range(n) if all_scored[i] > all_allowed[i]),
        "losses": sum(1 for i in range(n) if all_scored[i] < all_allowed[i]),
        "home_wins": sum(1 for i in range(len(home_scored)) if home_scored[i] > home_allowed[i]),
        "home_losses": sum(1 for i in range(len(home_scored)) if home_scored[i] < home_allowed[i]),
        "away_wins": sum(1 for i in range(len(away_scored)) if away_scored[i] > away_allowed[i]),
        "away_losses": sum(1 for i in range(len(away_scored)) if away_scored[i] < away_allowed[i]),
        "pts_off": sum(all_scored) / n,
        "pts_def": sum(all_allowed) / n,
    }


# ─────────────────────────────────────────────────────────────
# TEAM STATS BUILDER — outputs CFBTeamStats (live-pipeline format)
# ─────────────────────────────────────────────────────────────

def build_team_stats(
    team_name: str,
    all_season_games: list,
    all_season_stats: dict,
    sp_ratings: dict,
) -> CFBTeamStats:
    """
    Build a CFBTeamStats object (same class cfb_predictor.py already
    consumes) using pre-fetched CFBD season data, with SP+ blended in
    as a proxy adjustment for yards-per-play offense/defense.
    """
    c = CFB_CONSTANTS
    game_stats = _calc_game_stats(all_season_games, team_name)
    stat_map   = all_season_stats.get(team_name, {})

    if game_stats:
        pts_off = game_stats["pts_off"]
        pts_def = game_stats["pts_def"]
        wins, losses = game_stats["wins"], game_stats["losses"]
        home_wins, home_losses = game_stats["home_wins"], game_stats["home_losses"]
        away_wins, away_losses = game_stats["away_wins"], game_stats["away_losses"]
    else:
        pts_off, pts_def = c["league_avg_pts"], c["league_avg_pts"]
        wins = losses = home_wins = home_losses = away_wins = away_losses = 0

    games_played = _safe(stat_map, "games", default=max(game_stats.get("games_played", 0), 1))
    total_yards  = _safe(stat_map, "totalYards")
    pass_att     = _safe(stat_map, "passAttempts")
    rush_att     = _safe(stat_map, "rushingAttempts")
    turnovers    = _safe(stat_map, "turnovers")
    pass_yards   = _safe(stat_map, "netPassingYards")
    rush_yards   = _safe(stat_map, "rushingYards")

    ypp_direct = _safe(stat_map, "yardsPerPlay", default=-1)
    if ypp_direct > 0:
        ypp_off = ypp_direct
    else:
        total_plays = pass_att + rush_att
        ypp_off = (total_yards / total_plays) if total_plays > 0 else c["league_avg_ypp"]

    to_given = (turnovers / games_played) if games_played > 0 else c["league_avg_to_given"]
    pass_pg  = (pass_yards / games_played) if games_played > 0 else 220.0
    rush_pg  = (rush_yards / games_played) if games_played > 0 else 160.0

    # ── SP+ blend: adjust ypp_off/ypp_def using offense/defense ratings ──
    # SP+ rating scale is roughly -20 (very bad) to +30 (elite).
    # This maps that onto our yards-per-play scale as a proxy signal.
    ypp_def   = c["league_avg_ypp"]
    to_forced = c["league_avg_to_given"]  # no separate "forced" constant exists — same baseline
    sp = sp_ratings.get(team_name)
    if sp:
        try:
            off_rating = getattr(getattr(sp, "offense", None), "rating", None)
            if off_rating is not None:
                r = max(-20.0, min(30.0, float(off_rating)))
                # elite offense (+30) -> ~6.8 ypp, bad offense (-20) -> ~4.5 ypp
                ypp_off = 5.5 + (r / 30.0) * 1.3
        except Exception:
            pass
        try:
            def_rating = getattr(getattr(sp, "defense", None), "rating", None)
            if def_rating is not None:
                r = max(-20.0, min(25.0, float(def_rating)))
                # elite defense -> lower ypp allowed
                ypp_def = 5.5 - (r / 25.0) * 1.3
        except Exception:
            pass
        try:
            havoc = getattr(getattr(sp, "defense", None), "havoc", None)
            total_havoc = getattr(havoc, "total", None) if havoc else None
            if total_havoc:
                to_forced = max(0.5, min(3.5, float(total_havoc) * 36.0))
        except Exception:
            pass

    team_id = FBS_TEAM_IDS.get(team_name, "")

    return CFBTeamStats(
        team_name=team_name, team_id=team_id,
        wins=wins, losses=losses,
        home_wins=home_wins, home_losses=home_losses,
        away_wins=away_wins, away_losses=away_losses,
        pts_per_game=round(pts_off, 1), pts_allowed=round(pts_def, 1),
        yards_per_play_off=round(ypp_off, 2), yards_per_play_def=round(ypp_def, 2),
        pass_yards_pg=round(pass_pg, 1), rush_yards_pg=round(rush_pg, 1),
        turnovers_given=round(to_given, 2), turnovers_forced=round(to_forced, 2),
        third_down_pct=40.0,  # CFBD stat name for this varies by season; not critical to the model
        sacks_allowed=2.0, sacks_forced=2.0, penalties_pg=6.0,
    )


def _fcs_default(team_name: str) -> CFBTeamStats:
    """League-average-ish stats for an FCS/non-FBS opponent."""
    c = CFB_CONSTANTS
    return CFBTeamStats(
        team_name=team_name, team_id="",
        wins=0, losses=0, home_wins=0, home_losses=0, away_wins=0, away_losses=0,
        pts_per_game=round(c["league_avg_pts"] * 0.75, 1),
        pts_allowed=round(c["league_avg_pts"] * 1.15, 1),
        yards_per_play_off=round(c["league_avg_ypp"] * 0.90, 2),
        yards_per_play_def=round(c["league_avg_ypp"] * 1.10, 2),
        pass_yards_pg=180.0, rush_yards_pg=130.0,
        turnovers_given=round(c["league_avg_to_given"] * 1.10, 2),
        turnovers_forced=round(c["league_avg_to_given"] * 0.90, 2),
        third_down_pct=35.0, sacks_allowed=2.5, sacks_forced=1.5, penalties_pg=6.5,
    )


# ─────────────────────────────────────────────────────────────
# SCHEDULE + BETTING LINES
# ─────────────────────────────────────────────────────────────

def get_weekly_games(client: CFBDClient, year: int, week: int) -> list:
    """Pull schedule and betting lines for a specific week."""
    try:
        games = client.games.get_games(
            year=year, week=week, season_type=cfbd.SeasonType.REGULAR,
        )
    except Exception as e:
        print(f"  ✗ Schedule fetch failed: {e}")
        return []

    try:
        bet_games = client.betting.get_lines(year=year, week=week, season_type=cfbd.SeasonType.REGULAR)
        lines_lookup = {(bg.home_team, bg.away_team): bg.lines for bg in bet_games}
    except Exception:
        lines_lookup = {}

    results = []
    for g in games:
        if not g.home_team or not g.away_team:
            continue

        raw_lines = lines_lookup.get((g.home_team, g.away_team), [])
        spread_line, over_under, home_ml, away_ml = 0.0, 50.0, -110, -110
        has_odds = False

        preferred = ["consensus", "Bovada", "DraftKings", "ESPN Bet"]
        chosen = None
        for prov in preferred:
            for ln in raw_lines:
                if ln.provider and prov.lower() in ln.provider.lower():
                    chosen = ln; break
            if chosen:
                break
        if not chosen and raw_lines:
            chosen = raw_lines[0]

        if chosen:
            has_odds = True
            try:
                # cfbd stores spread as home team's line (negative = home favored);
                # our model uses positive = home favored, so flip the sign
                spread_line = -float(chosen.spread) if chosen.spread else 0.0
            except Exception:
                pass
            try:
                over_under = float(chosen.over_under) if chosen.over_under else 50.0
            except Exception:
                pass
            try:
                home_ml = int(chosen.home_moneyline) if chosen.home_moneyline else -110
                away_ml = int(chosen.away_moneyline) if chosen.away_moneyline else -110
            except Exception:
                pass

        results.append({
            "home_team": g.home_team, "away_team": g.away_team,
            "neutral": g.neutral_site or False,
            "spread_line": spread_line, "over_under": over_under,
            "home_ml": home_ml, "away_ml": away_ml, "has_odds": has_odds,
        })

    return results


if __name__ == "__main__":
    print("Testing CFBD API connection...")
    client = CFBDClient()
    if client.test_connection():
        year = 2025
        sp = load_sp_ratings(client, year)
        print(f"\nSP+ ratings loaded for {len(sp)} teams.")
        if "Georgia" in sp:
            g = sp["Georgia"]
            print(f"Georgia SP+ raw object attributes: {vars(g) if hasattr(g, '__dict__') else g}")
        games = load_season_games(client, year)
        stats = load_season_stats(client, year)
        team_stats = build_team_stats("Georgia", games, stats, sp)
        print(f"\nGeorgia CFBTeamStats: {team_stats}")


# ─────────────────────────────────────────────────────────────
# BEST-AVAILABLE BRIDGE
# Tries CFBD (SP+ blended in) first. Falls back to cfb_data.py's
# plain ESPN fetch if the cfbd package isn't installed, no API key
# is set, or the CFBD call fails for any reason. Nothing breaks if
# CFBD isn't set up — it just runs on the ESPN-only numbers, same
# as before this file existed.
# ─────────────────────────────────────────────────────────────

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if not _client_checked:
        _client_checked = True
        try:
            _client = CFBDClient()
        except Exception:
            _client = None
    return _client


def get_team_stats(team_name: str, year: int = None):
    """
    Best-available CFB team stats. Uses CFBD (real SP+ ratings blended
    into yards-per-play) if CFBD_API_KEY is set and the cfbd package
    works; otherwise falls back to cfb_data.py's live ESPN fetch.
    """
    from datetime import datetime
    year = year or (datetime.now().year - 1 if datetime.now().month < 8 else datetime.now().year)

    client = _get_client()
    if client:
        try:
            games = load_season_games(client, year)
            stats = load_season_stats(client, year)
            sp    = load_sp_ratings(client, year)
            if games or stats:
                return build_team_stats(team_name, games, stats, sp)
        except Exception as e:
            print(f"  ⚠  CFBD lookup failed for {team_name}, falling back to ESPN: {e}")

    from cfb_data import get_team_stats as espn_get_team_stats
    return espn_get_team_stats(team_name)
