"""
data_pipeline.py
=================
Fetches all enhanced data from cfbd for the prediction engine.

Pulls (in 6 API calls total for the season):
  1. Multi-year game results (3 seasons)
  2. Advanced season stats (EPA, success rate, pace, havoc)
  3. SP+ ratings
  4. Elo ratings
  5. Betting lines (for ATS record + line movement)
  6. Venue/team location data (for travel calculation)

Everything is cached per session. Subsequent teams in the same
run use the cached data with zero additional API calls.
"""

import time
from typing import Optional, Dict, List
from enhanced_data import (
    AdvancedMetrics, MultiYearProfile, ATSRecord,
    GameContext, EnhancedProfile
)
from situational import TEAM_COORDINATES, calc_travel_miles, haversine_miles

try:
    import cfbd
    CFBD_AVAILABLE = True
except ImportError:
    CFBD_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# SESSION CACHE
# All data fetched once per session per year.
# ─────────────────────────────────────────────────────────────

_cache = {}   # {key: data}


def _get(key):
    return _cache.get(key)


def _set(key, value):
    _cache[key] = value
    return value


# ─────────────────────────────────────────────────────────────
# YEAR WEIGHTS
# ─────────────────────────────────────────────────────────────

YEAR_WEIGHTS = {
    0: 0.50,   # most recent year
    1: 0.30,   # one year prior
    2: 0.20,   # two years prior
}


# ─────────────────────────────────────────────────────────────
# BULK DATA LOADERS
# ─────────────────────────────────────────────────────────────

def load_all_games(client, year: int) -> list:
    """All completed regular season games for a year."""
    key = f"games_{year}"
    if _get(key) is not None:
        return _get(key)
    try:
        raw = client.games.get_games(year=year)
        completed = [g for g in raw if g.home_points is not None and g.away_points is not None]
        print(f"  ✓ Games {year}: {len(completed)} completed")
        return _set(key, completed)
    except Exception as e:
        print(f"  ⚠ Games {year} failed: {e}")
        return _set(key, [])


def load_all_stats(client, year: int) -> dict:
    """All team season stats keyed by {team: {stat_name: value}}."""
    key = f"stats_{year}"
    if _get(key) is not None:
        return _get(key)
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
            except:
                pass
        print(f"  ✓ Stats {year}: {len(lookup)} teams")
        return _set(key, lookup)
    except Exception as e:
        print(f"  ⚠ Stats {year} failed: {e}")
        return _set(key, {})


def load_advanced_stats(client, year: int) -> dict:
    """Advanced stats (EPA, success rate, pace, havoc) keyed by team name."""
    key = f"advanced_{year}"
    if _get(key) is not None:
        return _get(key)
    try:
        raw = client.stats.get_advanced_season_stats(year=year, exclude_garbage_time=True)
        lookup = {}
        for a in raw:
            if not a.team:
                continue
            off = a.offense or {}
            dfn = a.defense or {}

            def gv(obj, attr, default=0.0):
                v = getattr(obj, attr, None) if obj else None
                return float(v) if v is not None else default

            lookup[a.team] = {
                "epa_off":           gv(off, "ppa", 0.0),
                "epa_def":           gv(dfn, "ppa", 0.0),
                "success_off":       gv(off, "success_rate", 0.42),
                "success_def":       gv(dfn, "success_rate", 0.42),
                "explosiveness_off": gv(off, "explosiveness", 1.0),
                "pace_off":          gv(off, "plays", 72.0),
                "havoc_def":         gv(getattr(dfn, "havoc", None), "total", 0.18),
            }
        print(f"  ✓ Advanced stats {year}: {len(lookup)} teams")
        return _set(key, lookup)
    except Exception as e:
        print(f"  ⚠ Advanced stats {year} failed: {e}")
        return _set(key, {})


def load_sp_ratings(client, year: int) -> dict:
    """SP+ ratings keyed by team name."""
    key = f"sp_{year}"
    if _get(key) is not None:
        return _get(key)
    try:
        raw = client.ratings.get_sp(year=year)
        lookup = {r.team: r for r in raw if r.team}
        print(f"  ✓ SP+ {year}: {len(lookup)} teams")
        return _set(key, lookup)
    except Exception as e:
        print(f"  ⚠ SP+ {year} failed: {e}")
        return _set(key, {})


def load_elo_ratings(client, year: int) -> dict:
    """Elo ratings keyed by team name."""
    key = f"elo_{year}"
    if _get(key) is not None:
        return _get(key)
    try:
        raw = client.ratings.get_elo(year=year)
        lookup = {}
        for r in raw:
            if r.team and r.elo:
                lookup[r.team] = float(r.elo)
        print(f"  ✓ Elo {year}: {len(lookup)} teams")
        return _set(key, lookup)
    except Exception as e:
        print(f"  ⚠ Elo {year} failed: {e}")
        return _set(key, {})


def load_betting_lines(client, year: int) -> list:
    """All betting lines for a season (for ATS calculation)."""
    key = f"lines_{year}"
    if _get(key) is not None:
        return _get(key)
    try:
        # Pull lines week by week (cfbd requires week parameter for full season)
        all_lines = []
        for week in range(1, 16):
            try:
                week_lines = client.betting.get_lines(year=year, week=week)
                all_lines.extend(week_lines)
                time.sleep(0.2)
            except:
                break
        print(f"  ✓ Betting lines {year}: {len(all_lines)} games")
        return _set(key, all_lines)
    except Exception as e:
        print(f"  ⚠ Betting lines {year} failed: {e}")
        return _set(key, [])


def load_venues(client) -> dict:
    """Team venue/location data for travel calculations."""
    key = "venues"
    if _get(key) is not None:
        return _get(key)
    try:
        teams = client.teams.get_teams(classification="fbs")
        lookup = {}
        for t in teams:
            if t.school and t.location:
                lat = getattr(t.location, "latitude", None)
                lon = getattr(t.location, "longitude", None)
                if lat and lon:
                    lookup[t.school] = (float(lat), float(lon))
        # Merge with hardcoded fallbacks
        for team, coords in TEAM_COORDINATES.items():
            if team not in lookup:
                lookup[team] = coords
        print(f"  ✓ Venue locations: {len(lookup)} teams")
        return _set(key, lookup)
    except Exception as e:
        print(f"  ⚠ Venues failed, using hardcoded coordinates: {e}")
        return _set(key, TEAM_COORDINATES)


# ─────────────────────────────────────────────────────────────
# GAME-LEVEL SCORING STATS (from games)
# ─────────────────────────────────────────────────────────────

def _game_scoring_stats(games: list, team: str) -> dict:
    """Calculate per-game scoring stats for a team from game list."""
    home_scored, home_allowed = [], []
    away_scored, away_allowed = [], []

    for g in games:
        hp, ap = float(g.home_points), float(g.away_points)
        if g.home_team == team:
            home_scored.append(hp)
            home_allowed.append(ap)
        elif g.away_team == team:
            away_scored.append(ap)
            away_allowed.append(hp)

    all_scored  = home_scored + away_scored
    all_allowed = home_allowed + away_allowed
    n = len(all_scored)
    if n == 0:
        return {}

    recent_n = min(5, n)
    return {
        "pts_off":  sum(all_scored)  / n,
        "pts_def":  sum(all_allowed) / n,
        "home_pts": sum(home_scored) / len(home_scored) if home_scored else sum(all_scored)/n,
        "away_pts": sum(away_scored) / len(away_scored) if away_scored else sum(all_scored)/n,
        "recent_off": sum(all_scored[-recent_n:])  / recent_n,
        "recent_def": sum(all_allowed[-recent_n:]) / recent_n,
        "n_games": n,
    }


# ─────────────────────────────────────────────────────────────
# MULTI-YEAR PROFILE BUILDER
# ─────────────────────────────────────────────────────────────

def build_multi_year_profile(client, team: str, base_year: int) -> MultiYearProfile:
    """
    Build weighted multi-year profile from last 3 seasons.
    base_year is the most recent completed season (e.g., 2025).
    """
    years = [base_year, base_year - 1, base_year - 2]
    weighted_off = 0.0
    weighted_def = 0.0
    weighted_epa_off = 0.0
    weighted_epa_def = 0.0
    total_weight = 0.0
    pts_by_year = []

    for i, year in enumerate(years):
        weight = YEAR_WEIGHTS.get(i, 0.0)
        games = load_all_games(client, year)
        stats = _game_scoring_stats(games, team)
        adv   = load_advanced_stats(client, year)
        adv_t = adv.get(team, {})

        if stats:
            weighted_off += stats["pts_off"] * weight
            weighted_def += stats["pts_def"] * weight
            total_weight += weight
            pts_by_year.append(stats["pts_off"])

        epa_off = adv_t.get("epa_off", 0.0)
        epa_def = adv_t.get("epa_def", 0.0)
        weighted_epa_off += epa_off * weight
        weighted_epa_def += epa_def * weight

    if total_weight == 0:
        return MultiYearProfile()

    # Trend: improvement from year-2 to year-1 to year-0
    trend_off = 0.0
    if len(pts_by_year) >= 2:
        trend_off = pts_by_year[0] - pts_by_year[1]   # positive = improving

    return MultiYearProfile(
        weighted_pts_off = round(weighted_off / total_weight, 1),
        weighted_pts_def = round(weighted_def / total_weight, 1),
        weighted_epa_off = round(weighted_epa_off / total_weight, 3),
        weighted_epa_def = round(weighted_epa_def / total_weight, 3),
        trend_off        = round(trend_off, 1),
        years_available  = len(pts_by_year),
    )


# ─────────────────────────────────────────────────────────────
# ATS RECORD BUILDER
# ─────────────────────────────────────────────────────────────

def _pick_best_line(lines_list: list) -> Optional[object]:
    """Pick the best available line (consensus or Bovada preferred)."""
    if not lines_list:
        return None
    preferred = ["consensus", "bovada", "draftkings"]
    for pref in preferred:
        for ln in lines_list:
            if ln.provider and pref in ln.provider.lower():
                return ln
    return lines_list[0]


def build_ats_record(client, team: str, base_year: int, years: int = 3) -> ATSRecord:
    """
    Calculate ATS record for a team over the last N seasons.
    Uses cfbd betting lines + game results.
    """
    record = ATSRecord()
    total_games = 0

    for yr in range(base_year, base_year - years, -1):
        games  = load_all_games(client, yr)
        lines  = load_betting_lines(client, yr)

        # Build lines lookup: (home_team, away_team) → GameLine
        lines_map = {}
        for bg in lines:
            key = (bg.home_team, bg.away_team)
            chosen = _pick_best_line(bg.lines)
            if chosen:
                lines_map[key] = chosen

        for g in games:
            if g.home_team != team and g.away_team != team:
                continue
            if g.home_points is None:
                continue

            key = (g.home_team, g.away_team)
            ln  = lines_map.get(key)
            if not ln or not ln.spread:
                continue

            try:
                spread = float(ln.spread)   # negative = home favored
            except:
                continue

            hp = float(g.home_points)
            ap = float(g.away_points)
            margin = hp - ap   # positive = home won by this much

            # Did team cover?
            is_home = g.home_team == team
            if is_home:
                # home needs to win by more than abs(spread) if favored
                # spread is negative if home is favored (e.g., -7 = home -7)
                # home covers if margin > -spread
                covered = margin > -spread
                push    = margin == -spread
            else:
                # away team; spread is from home perspective
                # away covers if margin < -spread (home didn't cover)
                covered = margin < -spread
                push    = margin == -spread

            if push:
                record.overall_p += 1
            elif covered:
                record.overall_w += 1
                if is_home:
                    record.home_w += 1
                else:
                    record.away_w += 1
            else:
                record.overall_l += 1
                if is_home:
                    record.home_l += 1
                else:
                    record.away_l += 1

            # Over/under
            if ln.over_under:
                try:
                    total_scored = hp + ap
                    total_line = float(ln.over_under)
                    if total_scored > total_line:
                        record.ou_over_w += 1
                    elif total_scored < total_line:
                        record.ou_under_w += 1
                except:
                    pass

            total_games += 1

    record.games_rated = total_games

    # Calculate percentages
    ats_decided = record.overall_w + record.overall_l
    if ats_decided > 0:
        record.overall_pct = round(record.overall_w / ats_decided, 3)

    home_decided = record.home_w + record.home_l
    if home_decided > 0:
        record.home_pct = round(record.home_w / home_decided, 3)

    away_decided = record.away_w + record.away_l
    if away_decided > 0:
        record.away_pct = round(record.away_w / away_decided, 3)

    ou_decided = record.ou_over_w + record.ou_under_w
    if ou_decided > 0:
        record.ou_pct = round(record.ou_over_w / ou_decided, 3)

    return record


# ─────────────────────────────────────────────────────────────
# ADVANCED METRICS BUILDER
# ─────────────────────────────────────────────────────────────

def build_advanced_metrics(client, team: str, year: int) -> AdvancedMetrics:
    """Build AdvancedMetrics from cfbd advanced stats + SP+ + Elo."""
    adv  = load_advanced_stats(client, year)
    sp   = load_sp_ratings(client, year)
    elo  = load_elo_ratings(client, year)

    adv_t = adv.get(team, {})
    sp_t  = sp.get(team)
    elo_t = elo.get(team, 1500.0)

    # SP+ defense rating (higher = better defense)
    sp_def_rating = 0.0
    sp_off_rating = 0.0
    if sp_t and sp_t.defense:
        sp_def_rating = float(getattr(sp_t.defense, "rating", 0) or 0)
    if sp_t and sp_t.offense:
        sp_off_rating = float(getattr(sp_t.offense, "rating", 0) or 0)

    return AdvancedMetrics(
        epa_off          = round(adv_t.get("epa_off", 0.0), 4),
        epa_def          = round(adv_t.get("epa_def", 0.0), 4),
        success_rate_off = round(adv_t.get("success_off", 0.42), 4),
        success_rate_def = round(adv_t.get("success_def", 0.42), 4),
        pace             = round(adv_t.get("pace_off", 72.0), 1),
        explosiveness    = round(adv_t.get("explosiveness_off", 1.0), 3),
        havoc            = round(adv_t.get("havoc_def", 0.18), 4),
        elo              = round(elo_t, 0),
        sp_rating        = round(sp_off_rating - sp_def_rating, 2),
    )


# ─────────────────────────────────────────────────────────────
# GAME CONTEXT BUILDER
# ─────────────────────────────────────────────────────────────

def build_game_context(
    client,
    game_meta: dict,
    home_team: str,
    away_team: str,
    schedule_year: int,
    week: int,
    venues: dict,
) -> GameContext:
    """
    Build GameContext for a specific game.
    Pulls weather from game record, calculates rest + travel,
    computes line movement from opening vs closing spread.
    """
    ctx = GameContext()

    # ── Line movement from game meta ──────────────────────────
    # cfbd GameLine has spread_open and over_under_open
    try:
        lines_key = f"lines_{schedule_year}_{week}"
        if _get(lines_key) is None:
            week_lines = client.betting.get_lines(
                year=schedule_year, week=week,
                season_type=cfbd.SeasonType.REGULAR,
            )
            _set(lines_key, {(bg.home_team, bg.away_team): bg.lines for bg in week_lines})

        game_lines = _get(lines_key) or {}
        chosen = _pick_best_line(game_lines.get((home_team, away_team), []))
        if chosen:
            if chosen.spread is not None and chosen.spread_open is not None:
                try:
                    closing = float(chosen.spread)
                    opening = float(chosen.spread_open)
                    ctx.opening_spread = opening
                    ctx.closing_spread = closing
                    # cfbd spread: negative = home favored
                    # movement toward home = closing is MORE negative than opening
                    ctx.line_movement = -(closing - opening)   # flip for display
                except:
                    pass
            if chosen.over_under is not None and chosen.over_under_open is not None:
                try:
                    ctx.opening_total = float(chosen.over_under_open)
                    ctx.closing_total = float(chosen.over_under)
                    ctx.total_movement = ctx.closing_total - ctx.opening_total
                except:
                    pass
    except:
        pass

    # ── Rest days (from game schedule) ────────────────────────
    # cfbd games have start_date; we'd need prior game to calc rest
    # Default to 7 (standard week) — enhanced by schedule data if available
    ctx.home_rest_days = game_meta.get("home_rest_days", 7)
    ctx.away_rest_days = game_meta.get("away_rest_days", 7)
    ctx.home_on_bye    = ctx.home_rest_days >= 14
    ctx.away_on_bye    = ctx.away_rest_days >= 14

    # ── Travel distance ───────────────────────────────────────
    home_coords = venues.get(home_team)
    away_coords = venues.get(away_team)
    if home_coords and away_coords:
        ctx.away_travel_miles = round(
            haversine_miles(away_coords[0], away_coords[1],
                           home_coords[0], home_coords[1]), 0)
        # Home team doesn't travel (true home game)
        ctx.home_travel_miles = 0.0

    # ── Weather from game record ──────────────────────────────
    try:
        games_key = f"games_{schedule_year}"
        games = _get(games_key) or []
        for g in games:
            if g.home_team == home_team and g.away_team == away_team:
                w = getattr(g, "weather", None)
                if w:
                    ctx.temp_f        = float(w.temperature) if getattr(w, "temperature", None) else None
                    ctx.wind_mph      = float(w.wind_speed)  if getattr(w, "wind_speed", None) else None
                    ctx.weather_cond  = getattr(w, "weather_condition", None)
                # Venue type from game
                ctx.is_dome = "dome" in str(getattr(g, "venue", "") or "").lower()
                break
    except:
        pass

    # Neutral site
    ctx.is_dome = game_meta.get("neutral", False) or ctx.is_dome

    return ctx


# ─────────────────────────────────────────────────────────────
# FULL ENHANCED PROFILE BUILDER
# ─────────────────────────────────────────────────────────────

def build_enhanced_profile(
    client,
    team: str,
    base_year: int,
    fbs_teams: set,
) -> EnhancedProfile:
    """
    Build a complete EnhancedProfile for a team.
    Uses pre-loaded cached data — no extra API calls per team.
    """
    from cfbd_api import CFB_CONSTANTS as c

    # FCS fallback
    if team not in fbs_teams:
        return _fcs_enhanced_profile(team)

    # ── Base scoring stats (most recent year) ─────────────────
    games      = load_all_games(client, base_year)
    stats      = _game_scoring_stats(games, team)
    stat_map   = load_all_stats(client, base_year).get(team, {})

    pts_off  = stats.get("pts_off",  c["league_avg_pts"])
    pts_def  = stats.get("pts_def",  c["league_avg_pts"])
    home_pts = stats.get("home_pts", pts_off * 1.06)
    away_pts = stats.get("away_pts", pts_off * 0.94)
    rec_off  = stats.get("recent_off", pts_off)
    rec_def  = stats.get("recent_def", pts_def)

    # YPP from stats
    ypp_direct = float(stat_map.get("yardsPerPlay", -1) or -1)
    if ypp_direct > 0:
        ypp_off = ypp_direct
    else:
        pass_yds = float(stat_map.get("passingYards", 0) or 0)
        rush_yds = float(stat_map.get("rushingYards", 0) or 0)
        plays    = float(stat_map.get("passAttempts", 0) or 0) + float(stat_map.get("rushingAttempts", 0) or 0)
        ypp_off  = (pass_yds + rush_yds) / plays if plays > 0 else c["league_avg_ypp"]

    to_given  = float(stat_map.get("turnovers", c["league_avg_to_given"] * 12) or 0)
    games_n   = float(stat_map.get("games", 12) or 12)
    to_given  = to_given / games_n if games_n > 0 else c["league_avg_to_given"]

    # YPP defense and TO forced from SP+/advanced
    sp_all = load_sp_ratings(client, base_year)
    sp_t   = sp_all.get(team)
    ypp_def   = c["league_avg_ypp"]
    to_forced = c["league_avg_to_forced"]
    sos       = 0.50

    if sp_t:
        if sp_t.defense:
            dr = float(getattr(sp_t.defense, "rating", 0) or 0)
            dr_clamped = max(-20.0, min(25.0, dr))
            ypp_def = 5.5 - (dr_clamped / 45.0) * 2.0
            ypp_def = max(3.5, min(7.5, ypp_def))
            havoc = getattr(sp_t.defense, "havoc", None)
            if havoc and getattr(havoc, "total", None):
                to_forced = max(0.5, min(3.5, float(havoc.total) * 72 / 2.0))
        if sp_t.sos is not None:
            raw_sos = float(sp_t.sos)
            sos = round((max(-15.0, min(10.0, raw_sos)) + 15.0) / 25.0, 3)

    # ── Advanced metrics ──────────────────────────────────────
    advanced = build_advanced_metrics(client, team, base_year)

    # ── Multi-year profile ────────────────────────────────────
    history = build_multi_year_profile(client, team, base_year)

    # ── ATS record (2-3 seasons) ──────────────────────────────
    ats = build_ats_record(client, team, base_year, years=3)

    return EnhancedProfile(
        team_name    = team,
        league       = "CFB",
        pts_off      = round(pts_off,  1),
        pts_def      = round(pts_def,  1),
        ypp_off      = round(ypp_off,  2),
        ypp_def      = round(ypp_def,  2),
        to_given     = round(to_given, 2),
        to_forced    = round(to_forced, 2),
        home_pts_off = round(home_pts, 1),
        away_pts_off = round(away_pts, 1),
        recent_off   = round(rec_off,  1),
        recent_def   = round(rec_def,  1),
        sos          = sos,
        injury_adj   = 0.0,
        advanced     = advanced,
        history      = history,
        ats          = ats,
    )


def _fcs_enhanced_profile(team: str) -> EnhancedProfile:
    """Capped stats for non-FBS opponents."""
    return EnhancedProfile(
        team_name    = team,
        league       = "CFB",
        pts_off      = 21.75,
        pts_def      = 33.35,
        ypp_off      = 5.4,
        ypp_def      = 6.6,
        to_given     = 1.76,
        to_forced    = 1.44,
        home_pts_off = 22.0,
        away_pts_off = 21.0,
        recent_off   = 21.75,
        recent_def   = 33.35,
        sos          = 0.30,
    )
