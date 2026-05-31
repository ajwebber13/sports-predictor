"""
enhanced_data.py
=================
Data structures for the enhanced prediction engine.

New structures:
  AdvancedMetrics  — EPA, success rate, pace, havoc (from cfbd advanced stats)
  MultiYearProfile — weighted 3-year historical ratings
  ATSRecord        — against the spread history
  GameContext      — rest, travel, weather, market signals
  EnhancedProfile  — wraps all of the above for one team
"""

from dataclasses import dataclass, field
from typing import Optional, Tuple


# ─────────────────────────────────────────────────────────────
# ADVANCED METRICS
# ─────────────────────────────────────────────────────────────

@dataclass
class AdvancedMetrics:
    """
    EPA and efficiency metrics from cfbd advanced season stats.

    epa_off        : Expected Points Added per play on offense
                     Positive = above average offense
    epa_def        : EPA per play ALLOWED on defense
                     Negative = better defense (suppresses opponent EPA)
    success_rate_off: Fraction of offensive plays gaining "enough" yards
                     (~42% = average FBS)
    success_rate_def: Fraction of opponent plays that succeed vs this defense
                     Lower = better defense
    pace           : Plays per game (higher = faster offense)
    explosiveness  : Rate of big plays (>= 20 yards) on offense
    havoc          : Defensive disruption rate (TFLs + sacks + INTs + PBUs + fumbles)
    elo            : Elo rating (1500 = average)
    sp_rating      : SP+ composite rating
    """
    epa_off:          float = 0.0
    epa_def:          float = 0.0
    success_rate_off: float = 0.42
    success_rate_def: float = 0.42
    pace:             float = 72.0   # avg plays per game
    explosiveness:    float = 1.0    # relative to average
    havoc:            float = 0.18   # avg havoc rate
    elo:              float = 1500.0
    sp_rating:        float = 0.0


# ─────────────────────────────────────────────────────────────
# MULTI-YEAR PROFILE
# ─────────────────────────────────────────────────────────────

@dataclass
class MultiYearProfile:
    """
    Weighted average of last 3 seasons' performance.

    Weights: 2025=50%, 2024=30%, 2023=20%
    Provides stability against one-year anomalies.

    weighted_pts_off : weighted avg pts scored per game
    weighted_pts_def : weighted avg pts allowed per game
    weighted_epa_off : weighted avg EPA per play offense
    weighted_epa_def : weighted avg EPA per play defense
    trend_off        : positive = improving offense year over year
    trend_def        : positive = improving defense year over year
    years_available  : how many years of data were found
    """
    weighted_pts_off: float = 0.0
    weighted_pts_def: float = 0.0
    weighted_epa_off: float = 0.0
    weighted_epa_def: float = 0.0
    trend_off:        float = 0.0   # pts/game change vs prior year
    trend_def:        float = 0.0
    years_available:  int   = 1


# ─────────────────────────────────────────────────────────────
# ATS RECORD
# ─────────────────────────────────────────────────────────────

@dataclass
class ATSRecord:
    """
    Against-the-spread historical record.

    A team covering >55% ATS historically has shown betting value.
    A team covering <45% ATS historically tends to underperform the line.

    Calculated from cfbd betting lines + game results.
    """
    overall_w:  int   = 0      # ATS wins
    overall_l:  int   = 0      # ATS losses
    overall_p:  int   = 0      # ATS pushes
    overall_pct: float = 0.50  # win % (pushes excluded)
    home_w:     int   = 0
    home_l:     int   = 0
    home_pct:   float = 0.50
    away_w:     int   = 0
    away_l:     int   = 0
    away_pct:   float = 0.50
    ou_over_w:  int   = 0      # over wins
    ou_under_w: int   = 0      # under wins
    ou_pct:     float = 0.50   # over %
    games_rated: int  = 0      # total games with line data

    def ats_signal(self) -> str:
        """Human-readable ATS signal."""
        if self.games_rated < 5:
            return "INSUFFICIENT DATA"
        if self.overall_pct >= 0.58:
            return "★★ STRONG ATS COVER TREND"
        if self.overall_pct >= 0.53:
            return "★  SLIGHT ATS COVER TREND"
        if self.overall_pct <= 0.42:
            return "✗✗ STRONG ATS FADE TREND"
        if self.overall_pct <= 0.47:
            return "✗  SLIGHT ATS FADE TREND"
        return "─  NEUTRAL ATS"


# ─────────────────────────────────────────────────────────────
# GAME CONTEXT
# ─────────────────────────────────────────────────────────────

@dataclass
class GameContext:
    """
    Situational and market context for a specific game.
    Passed to the predictor alongside team stats.

    Rest / schedule:
      home_rest_days  : days since home team's last game
      away_rest_days  : days since away team's last game
      home_on_bye     : True if home team had a bye week (14+ days rest)
      away_on_bye     : True if away team had a bye week

    Weather (for outdoor games):
      temp_f          : temperature in Fahrenheit
      wind_mph        : wind speed in mph
      weather_cond    : "Clear", "Cloudy", "Rain", "Snow", etc.
      is_dome         : True if indoor/dome stadium
      surface         : "Grass" or "Turf"

    Travel:
      home_travel_miles : how far home team traveled (0 for true home games)
      away_travel_miles : miles the away team traveled

    Market signals (from cfbd opening vs closing lines):
      opening_spread  : Vegas spread when line first opened
      closing_spread  : current/closing spread
      line_movement   : closing - opening (positive = moved toward home team)
      opening_total   : opening over/under
      closing_total   : current over/under
      total_movement  : closing - opening total
    """
    # Rest
    home_rest_days:     int   = 7
    away_rest_days:     int   = 7
    home_on_bye:        bool  = False
    away_on_bye:        bool  = False

    # Weather
    temp_f:             Optional[float] = None
    wind_mph:           Optional[float] = None
    weather_cond:       Optional[str]   = None
    is_dome:            bool  = False
    surface:            str   = "Grass"

    # Travel
    home_travel_miles:  float = 0.0
    away_travel_miles:  float = 0.0

    # Market
    opening_spread:     Optional[float] = None
    closing_spread:     Optional[float] = None
    line_movement:      Optional[float] = None   # positive = moved to home
    opening_total:      Optional[float] = None
    closing_total:      Optional[float] = None
    total_movement:     Optional[float] = None

    def weather_summary(self) -> str:
        if self.is_dome:
            return "DOME"
        parts = []
        if self.temp_f is not None:
            parts.append(f"{self.temp_f:.0f}°F")
        if self.wind_mph is not None and self.wind_mph > 0:
            parts.append(f"wind {self.wind_mph:.0f}mph")
        if self.weather_cond:
            parts.append(self.weather_cond)
        return ", ".join(parts) if parts else "Unknown"

    def market_signal(self) -> str:
        if self.line_movement is None:
            return "NO LINE MOVEMENT DATA"
        if abs(self.line_movement) < 0.5:
            return "─  MINIMAL MOVEMENT"
        direction = "HOME" if self.line_movement > 0 else "AWAY"
        amount = abs(self.line_movement)
        if amount >= 3:
            return f"★★★ SHARP MONEY → {direction} ({amount:+.1f} pts)"
        if amount >= 1.5:
            return f"★★  MODERATE MOVE → {direction} ({amount:+.1f} pts)"
        return f"★   SLIGHT MOVE → {direction} ({amount:+.1f} pts)"


# ─────────────────────────────────────────────────────────────
# ENHANCED TEAM PROFILE
# ─────────────────────────────────────────────────────────────

@dataclass
class EnhancedProfile:
    """
    Full enhanced profile for a team — wraps all data sources.
    Passed to the enhanced predictor.

    The base TeamStats is kept for backward compatibility.
    All new signals are additive.
    """
    # Original stats (required, backward compatible)
    team_name:    str = ""
    league:       str = "CFB"

    # Scoring (from games, multi-year weighted)
    pts_off:      float = 29.0
    pts_def:      float = 29.0
    ypp_off:      float = 6.0
    ypp_def:      float = 6.0
    to_given:     float = 1.6
    to_forced:    float = 1.6
    home_pts_off: float = 30.0
    away_pts_off: float = 28.0
    recent_off:   float = 29.0
    recent_def:   float = 29.0
    sos:          float = 0.5
    injury_adj:   float = 0.0

    # New: Advanced metrics
    advanced:     AdvancedMetrics = field(default_factory=AdvancedMetrics)

    # New: Multi-year historical
    history:      MultiYearProfile = field(default_factory=MultiYearProfile)

    # New: ATS record
    ats:          ATSRecord = field(default_factory=ATSRecord)

    def to_team_stats(self):
        """Convert back to original TeamStats for compatibility."""
        from predictor import TeamStats
        return TeamStats(
            name               = self.team_name,
            league             = self.league,
            pts_per_game_off   = self.pts_off,
            yards_per_play_off = self.ypp_off,
            pts_per_game_def   = self.pts_def,
            yards_per_play_def = self.ypp_def,
            turnovers_given    = self.to_given,
            turnovers_forced   = self.to_forced,
            home_pts_avg       = self.home_pts_off,
            away_pts_avg       = self.away_pts_off,
            recent_pts_scored  = self.recent_off,
            recent_pts_allowed = self.recent_def,
            sos                = self.sos,
            injury_adj         = self.injury_adj,
        )
