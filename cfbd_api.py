"""
cfbd_api.py
============
College Football Data API integration.
Uses the official cfbd Python library.

Setup (one time):
  1. Register for a free API key at: https://collegefootballdata.com/key
  2. Set your key in one of two ways:
       Option A — environment variable (recommended):
         Windows: setx CFBD_API_KEY "your_key_here"
         Mac/Linux: export CFBD_API_KEY="your_key_here"
       Option B — pass key directly to CFBDClient(api_key="your_key")

Install:
  pip install cfbd

Key fix in this version:
  Previously fetched game results per team (198 API calls for 99 games).
  Now fetches the entire season once and calculates all team defensive
  stats from that single dataset. Fixes the DEF RTG = 1.000 bug.
"""

import os
import time
from typing import Optional
import cfbd
from predictor import TeamStats, MatchupInput, CFB_CONSTANTS


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
# SEASON GAME CACHE
# Fetches ALL completed games for a season in ONE API call.
# Used to calculate defensive stats for every team without
# making per-team requests that hit rate limits.
# ─────────────────────────────────────────────────────────────

_season_games_cache = {}   # {year: [Game, ...]}
_season_stats_cache = {}   # {year: {team_name: stat_dict}}
_sp_ratings_cache   = {}   # {year: {team_name: TeamSP}}


def load_season_games(client: CFBDClient, year: int) -> list:
    """
    Fetch ALL completed regular-season games for a year.
    Cached after first call — only hits the API once per session.
    """
    if year in _season_games_cache:
        return _season_games_cache[year]

    print(f"  Loading {year} season game results (one-time fetch)...")
    try:
        # No team filter — get everything at once
        raw = client.games.get_games(year=year)
        completed = [
            g for g in raw
            if g.home_points is not None
            and g.away_points is not None
            and getattr(g, "season_type", "regular") in ("regular", "postseason", None, "")
        ]
        _season_games_cache[year] = completed
        print(f"  ✓ {len(completed)} completed games loaded for {year}")
        return completed
    except Exception as e:
        print(f"  ✗ Season games fetch failed: {e}")
        _season_games_cache[year] = []
        return []


def load_season_stats(client: CFBDClient, year: int) -> dict:
    """
    Fetch ALL team season stats for a year in one call.
    Returns {team_name: {stat_name: value}}.
    """
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
    """
    Fetch SP+ ratings for all teams in one call.
    Returns {team_name: TeamSP}.
    """
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


def _normalize_sos(raw_sos) -> float:
    """SP+ SOS (~-15 to +10) → 0.0–1.0 scale."""
    if raw_sos is None:
        return 0.50
    return round((max(-15.0, min(10.0, float(raw_sos))) + 15.0) / 25.0, 3)


def _calc_game_stats(all_games: list, team_name: str) -> dict:
    """
    Calculate scoring stats for a team from the full season game list.
    Returns per-game averages for pts scored, pts allowed, home/away splits,
    and recent form (last 5 games).
    """
    home_scored  = []
    home_allowed = []
    away_scored  = []
    away_allowed = []

    for g in all_games:
        hp = float(g.home_points)
        ap = float(g.away_points)
        if g.home_team == team_name:
            home_scored.append(hp)
            home_allowed.append(ap)
        elif g.away_team == team_name:
            away_scored.append(ap)
            away_allowed.append(hp)

    all_scored  = home_scored  + away_scored
    all_allowed = home_allowed + away_allowed
    n = len(all_scored)

    if n == 0:
        return {}

    # Sort all games by index (approximate chronological order)
    recent_n = min(5, n)
    recent_scored  = sum(all_scored[-recent_n:])  / recent_n
    recent_allowed = sum(all_allowed[-recent_n:]) / recent_n

    return {
        "games_played":   n,
        "pts_off":        sum(all_scored)   / n,
        "pts_def":        sum(all_allowed)  / n,
        "home_pts":       sum(home_scored)  / len(home_scored)  if home_scored  else sum(all_scored) / n * 1.06,
        "away_pts":       sum(away_scored)  / len(away_scored)  if away_scored  else sum(all_scored) / n * 0.94,
        "recent_scored":  recent_scored,
        "recent_allowed": recent_allowed,
    }


# ─────────────────────────────────────────────────────────────
# TEAM STATS BUILDER
# ─────────────────────────────────────────────────────────────

def build_team_stats(
    team_name:       str,
    all_season_games: list,
    all_season_stats: dict,
    sp_ratings:       dict,
    year:            int,
) -> TeamStats:
    """
    Build a TeamStats object using pre-fetched season data.

    all_season_games : all completed games for the year (from load_season_games)
    all_season_stats : all team stats for the year (from load_season_stats)
    sp_ratings       : SP+ ratings dict (from load_sp_ratings)
    """
    c = CFB_CONSTANTS

    # ── Offensive stats from season stats lookup ──────────────
    stat_map = all_season_stats.get(team_name, {})
    games_played = _safe(stat_map, "games", default=12.0)

    total_pts  = _safe(stat_map, "points")
    total_yards = _safe(stat_map, "totalYards")
    pass_att   = _safe(stat_map, "passAttempts")
    rush_att   = _safe(stat_map, "rushingAttempts")
    turnovers  = _safe(stat_map, "turnovers")

    pts_off = (total_pts / games_played) if games_played > 0 else c["league_avg_pts"]

    ypp_direct = _safe(stat_map, "yardsPerPlay", default=-1)
    if ypp_direct > 0:
        ypp_off = ypp_direct
    else:
        total_plays = pass_att + rush_att
        ypp_off = (total_yards / total_plays) if total_plays > 0 else c["league_avg_ypp"]

    to_given = (turnovers / games_played) if games_played > 0 else c["league_avg_to_given"]

    # ── All stats from game results (single pre-fetched dataset) ──
    game_stats = _calc_game_stats(all_season_games, team_name)

    if game_stats:
        # Use game-derived scoring (more accurate than stat lookup)
        pts_off_g  = game_stats["pts_off"]
        pts_def    = game_stats["pts_def"]
        home_pts   = game_stats["home_pts"]
        away_pts   = game_stats["away_pts"]
        rec_scored = game_stats["recent_scored"]
        rec_allow  = game_stats["recent_allowed"]
        n_games    = game_stats["games_played"]

        # Blend stat lookup pts with game-derived pts (stat lookup more complete)
        if pts_off > 0:
            pts_off = (pts_off * 0.6 + pts_off_g * 0.4)
        else:
            pts_off = pts_off_g
    else:
        # No game data found — use league averages for defense
        pts_def    = c["league_avg_pts"]
        home_pts   = pts_off * 1.06
        away_pts   = pts_off * 0.94
        rec_scored = pts_off
        rec_allow  = pts_def

    # ── Defensive yards per play from advanced stats ──────────
    ypp_def   = c["league_avg_ypp"]
    to_forced = c["league_avg_to_forced"]
    try:
        # Use SP+ offense/defense ratings as proxy for YPP
        sp = sp_ratings.get(team_name)
        if sp and sp.defense:
            def_rating = getattr(sp.defense, "rating", None)
            if def_rating is not None:
                # SP+ defense rating: higher = better defense
                # Typical range: -20 (bad) to +25 (elite)
                # Map to YPP allowed: elite def → ~4.5 YPP, bad def → ~6.5 YPP
                dr = float(def_rating)
                dr_clamped = max(-20.0, min(25.0, dr))
                ypp_def = 5.5 - (dr_clamped / 45.0) * 2.0
                ypp_def = max(3.5, min(7.5, ypp_def))

        if sp and sp.defense:
            havoc = getattr(sp.defense, "havoc", None)
            if havoc and hasattr(havoc, "total") and havoc.total:
                avg_plays = 72
                to_forced = max(0.5, min(3.5, float(havoc.total) * avg_plays / 2.0))
    except Exception:
        pass

    # ── Strength of schedule ──────────────────────────────────
    sos = 0.50
    try:
        sp = sp_ratings.get(team_name)
        if sp and sp.sos is not None:
            sos = _normalize_sos(sp.sos)
    except Exception:
        pass

    return TeamStats(
        name               = team_name,
        league             = "CFB",
        pts_per_game_off   = round(pts_off,     1),
        yards_per_play_off = round(ypp_off,     2),
        pts_per_game_def   = round(pts_def,     1),
        yards_per_play_def = round(ypp_def,     2),
        turnovers_given    = round(to_given,    2),
        turnovers_forced   = round(to_forced,   2),
        home_pts_avg       = round(home_pts,    1),
        away_pts_avg       = round(away_pts,    1),
        recent_pts_scored  = round(rec_scored,  1),
        recent_pts_allowed = round(rec_allow,   1),
        sos                = sos,
        injury_adj         = 0.0,
    )


# ─────────────────────────────────────────────────────────────
# SCHEDULE + BETTING LINES
# ─────────────────────────────────────────────────────────────

def get_weekly_games(client: CFBDClient, year: int, week: int,
                     classification: str = "fbs") -> list:
    """Pull schedule and betting lines for a specific week."""
    try:
        div   = cfbd.DivisionClassification(classification) if classification else None
        games = client.games.get_games(
            year=year, week=week,
            season_type=cfbd.SeasonType.REGULAR,
            classification=div,
        )
    except Exception as e:
        print(f"  ✗ Schedule fetch failed: {e}")
        return []

    # Fetch betting lines
    try:
        bet_games = client.betting.get_lines(
            year=year, week=week,
            season_type=cfbd.SeasonType.REGULAR,
        )
        lines_lookup = {}
        for bg in bet_games:
            key = (bg.home_team, bg.away_team)
            lines_lookup[key] = bg.lines
    except Exception:
        lines_lookup = {}

    results = []
    for g in games:
        if not g.home_team or not g.away_team:
            continue

        key        = (g.home_team, g.away_team)
        raw_lines  = lines_lookup.get(key, [])

        spread_line = 0.0
        over_under  = 50.0
        home_ml     = -110
        away_ml     = -110
        has_odds    = False
        odds_source = "none"

        # Pick best available line
        preferred   = ["consensus", "Bovada", "DraftKings", "ESPN Bet"]
        chosen_line = None
        for prov in preferred:
            for ln in raw_lines:
                if ln.provider and prov.lower() in ln.provider.lower():
                    chosen_line = ln
                    break
            if chosen_line:
                break
        if not chosen_line and raw_lines:
            chosen_line = raw_lines[0]

        if chosen_line:
            has_odds    = True
            odds_source = chosen_line.provider or "unknown"
            try:
                raw_spread  = float(chosen_line.spread) if chosen_line.spread else 0.0
                # cfbd stores spread as home team's line (negative = home favored)
                # Our model: positive = home favored → flip sign
                spread_line = -raw_spread
            except Exception:
                spread_line = 0.0
            try:
                over_under = float(chosen_line.over_under) if chosen_line.over_under else 50.0
            except Exception:
                over_under = 50.0
            try:
                home_ml = int(chosen_line.home_moneyline) if chosen_line.home_moneyline else -110
                away_ml = int(chosen_line.away_moneyline) if chosen_line.away_moneyline else -110
            except Exception:
                home_ml = -110
                away_ml = -110

        def _is_fbs(cls) -> bool:
            if cls is None:
                return True
            v = cls.value if hasattr(cls, "value") else str(cls)
            return str(v).lower() == "fbs"

        results.append({
            "game_id":     g.id,
            "home_team":   g.home_team,
            "away_team":   g.away_team,
            "neutral":     g.neutral_site or False,
            "spread_line": spread_line,
            "over_under":  over_under,
            "home_ml":     home_ml,
            "away_ml":     away_ml,
            "has_odds":    has_odds,
            "odds_source": odds_source,
            "home_points": g.home_points,
            "away_points": g.away_points,
            "completed":   g.completed,
            "home_is_fbs": _is_fbs(getattr(g, "home_classification", None)),
            "away_is_fbs": _is_fbs(getattr(g, "away_classification", None)),
        })

    return results


# ─────────────────────────────────────────────────────────────
# FCS TEAM DEFAULT
# FCS teams use league-average FBS stats so their non-FBS
# season numbers don't inflate or deflate FBS predictions.
# The FBS home team will still be favored via home advantage
# and the matchup context.
# ─────────────────────────────────────────────────────────────

def _fcs_default(team_name: str) -> TeamStats:
    """League-average stats for any non-FBS opponent."""
    c = CFB_CONSTANTS
    return TeamStats(
        name               = team_name,
        league             = "CFB",
        pts_per_game_off   = c["league_avg_pts"] * 0.75,   # FCS offense ~75% of FBS avg
        yards_per_play_off = c["league_avg_ypp"]  * 0.90,
        pts_per_game_def   = c["league_avg_pts"]  * 1.15,  # FCS defense allows more
        yards_per_play_def = c["league_avg_ypp"]  * 1.10,
        turnovers_given    = c["league_avg_to_given"]  * 1.10,
        turnovers_forced   = c["league_avg_to_forced"] * 0.90,
        home_pts_avg       = c["league_avg_pts"] * 0.75,
        away_pts_avg       = c["league_avg_pts"] * 0.70,
        recent_pts_scored  = c["league_avg_pts"] * 0.75,
        recent_pts_allowed = c["league_avg_pts"] * 1.15,
        sos                = 0.30,
        injury_adj         = 0.0,
    )


# ─────────────────────────────────────────────────────────────
# FULL PIPELINE
# ─────────────────────────────────────────────────────────────

def build_weekly_matchups(
    client:      CFBDClient,
    year:        int,
    week:        int,
    stats_year:  int,
    simulations: int = 10000,
    limit:       Optional[int] = None,
) -> list:
    """
    Full pipeline for a CFB week.

    Key improvement: pre-fetches all season data in 3 API calls total,
    then builds every team's stats locally. No per-team API calls.
    """
    print(f"\n  Pulling CFB Week {week} schedule ({year})...")
    games = get_weekly_games(client, year, week)

    if not games:
        print("  No games found.")
        return []

    if limit:
        games = games[:limit]

    # ── Pre-fetch all season data (3 calls total) ─────────────
    all_season_games = load_season_games(client, stats_year)
    all_season_stats = load_season_stats(client, stats_year)
    sp_ratings       = load_sp_ratings(client, stats_year)

    print(f"\n  Found {len(games)} games. Building predictions...")

    matchups = []
    for i, game in enumerate(games, 1):
        ht = game["home_team"]
        at = game["away_team"]
        home_fbs = game.get("home_is_fbs", True)
        away_fbs = game.get("away_is_fbs", True)
        fcs_note = ""
        if not home_fbs:
            fcs_note += f" [FCS: {ht}]"
        if not away_fbs:
            fcs_note += f" [FCS: {at}]"
        print(f"  [{i}/{len(games)}] {at} @ {ht}{fcs_note}")

        # FCS teams: use league averages so their FCS stats don't skew the model
        home_stats = build_team_stats(ht, all_season_games, all_season_stats, sp_ratings, stats_year) if home_fbs else _fcs_default(ht)
        away_stats = build_team_stats(at, all_season_games, all_season_stats, sp_ratings, stats_year) if away_fbs else _fcs_default(at)

        if not game["has_odds"]:
            print(f"    ⚠  No odds available — using defaults")

        matchup = MatchupInput(
            team_a          = home_stats,
            team_b          = away_stats,
            spread_line     = game["spread_line"],
            over_under_line = game["over_under"],
            team_a_odds     = game["home_ml"],
            team_b_odds     = game["away_ml"],
            neutral_site    = game["neutral"],
            team_a_is_home  = True,
            simulations     = simulations,
        )
        matchups.append((matchup, game))

    return matchups
