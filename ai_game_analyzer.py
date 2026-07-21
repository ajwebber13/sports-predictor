"""
ai_game_analyzer.py

Game-level counterpart to ai_prop_analyzer.py's generate_prop_analysis().
Same philosophy: templated, deterministic reasoning built from real
inputs your engines already validated — no LLM call, no new data
collection. Matches your locked "Knowledge Layer as byproduct" principle.

WIRED AGAINST REAL RETURN SHAPES (confirmed from ranking_engine.py and
team_form_engine.py, pulled 2026-07-19):

ranking_engine.get_rankings(sport) returns a list of dicts, one per
team, each with:
    team, sport, power_score,
    components: {elo_quality, form, efficiency, efficiency_is_real_data, sos}
    raw: {elo, elo_games_played, elo_reliability, adjusted_elo,
          schedule_difficulty, sos_adjustment_applied, avg_opponent_elo,
          win_percentage, current_streak}

team_form_engine.get_team_form(team, sport) returns:
    team, sport, games_tracked, current_streak {type, length},
    last_5 {wins, losses, record}, last_10 {wins, losses, record},
    win_percentage, avg_edge, avg_model_probability,
    games_model_backed, last_game_date, recent_games, insufficient_sample

USAGE:
    from ranking_engine import get_rankings
    rankings = {r["team"]: r for r in get_rankings(sport)}
    ctx = build_game_context(sport, home_team, away_team, rankings)
    # then per MarketPick:
    reasoning = generate_game_reasoning(ctx, pick)
"""

from dataclasses import dataclass, replace
from typing import Optional

from game_pick_selector import MarketPick


@dataclass
class TeamContext:
    name: str
    power_score: Optional[float] = None
    elo: Optional[float] = None
    win_percentage: Optional[float] = None     # 0-1 scale (raw.win_percentage)
    last_10_record: Optional[str] = None        # e.g. "8-2" (from team_form_engine)
    streak_type: Optional[str] = None            # "win" | "loss"
    streak_length: Optional[int] = None
    schedule_difficulty: Optional[float] = None  # raw.schedule_difficulty, capped +/-50
    efficiency_score: Optional[float] = None      # components.efficiency, 0-100 normalized
    efficiency_is_real: bool = False


@dataclass
class GameContext:
    sport: str
    home: TeamContext
    away: TeamContext


def build_team_context(team: str, rankings_by_team: dict) -> TeamContext:
    """rankings_by_team = {team_name: <one row from ranking_engine.get_rankings()>}"""
    r = rankings_by_team.get(team)
    if not r:
        return TeamContext(name=team)

    raw = r.get("raw", {})
    components = r.get("components", {})
    streak = raw.get("current_streak") or {}

    return TeamContext(
        name=team,
        power_score=r.get("power_score"),
        elo=raw.get("elo"),
        win_percentage=raw.get("win_percentage"),
        streak_type=streak.get("type"),
        streak_length=streak.get("length"),
        schedule_difficulty=raw.get("schedule_difficulty"),
        efficiency_score=components.get("efficiency"),
        efficiency_is_real=components.get("efficiency_is_real_data", False),
    )


def attach_last10_record(ctx: TeamContext, team_form: dict) -> TeamContext:
    """team_form = output of team_form_engine.get_team_form(team, sport). Optional
    enrichment — last_10.record isn't in ranking_engine's output, only
    team_form_engine's, so this is a separate call if you want it."""
    if team_form and not team_form.get("insufficient_sample"):
        last10 = team_form.get("last_10", {})
        return replace(ctx, last_10_record=last10.get("record"))
    return ctx


def build_game_context(sport: str, home_team: str, away_team: str, rankings_by_team: dict) -> GameContext:
    return GameContext(
        sport=sport,
        home=build_team_context(home_team, rankings_by_team),
        away=build_team_context(away_team, rankings_by_team),
    )


# ---------------------------------------------------------------------------
# Reasoning clause builders — each returns None if data isn't available.
# ---------------------------------------------------------------------------

def _clause_power_gap(picked: TeamContext, other: TeamContext) -> Optional[str]:
    if picked.power_score is None or other.power_score is None:
        return None
    gap = picked.power_score - other.power_score
    if abs(gap) < 3:
        return f"{picked.name} and {other.name} grade out nearly even on Power Score"
    if gap > 0:
        return f"{picked.name} holds a real edge in Power Score ({picked.power_score:.1f} vs {other.power_score:.1f})"
    return f"{picked.name} actually grades lower in Power Score ({picked.power_score:.1f} vs {other.power_score:.1f}), a value angle rather than a form pick"


def _clause_streak(picked: TeamContext) -> Optional[str]:
    if not picked.streak_type or not picked.streak_length:
        return None
    verb = "winning" if picked.streak_type == "win" else "on a"
    noun = "streak" if picked.streak_type == "win" else "losing streak"
    return f"{picked.name} is on a {picked.streak_length}-game {noun}"


def _clause_last10(picked: TeamContext) -> Optional[str]:
    if not picked.last_10_record:
        return None
    return f"{picked.last_10_record} over their last 10"


def _clause_sos(picked: TeamContext, other: TeamContext) -> Optional[str]:
    if picked.schedule_difficulty is None or other.schedule_difficulty is None:
        return None
    gap = picked.schedule_difficulty - other.schedule_difficulty
    if abs(gap) < 5:
        return None
    tougher = picked.name if gap > 0 else other.name
    return f"{tougher} has faced the tougher schedule to date"


def _clause_efficiency(picked: TeamContext, other: TeamContext) -> Optional[str]:
    if not other.efficiency_is_real or other.efficiency_score is None:
        return None
    if other.efficiency_score < 40:
        return f"{other.name} grades weak on efficiency, a favorable matchup"
    if other.efficiency_score > 65:
        return f"{other.name} grades strong on efficiency, a tougher-than-usual matchup"
    return None


def _clause_edge(pick: MarketPick) -> str:
    if pick.market == "moneyline" and pick.win_prob is not None:
        return f"model gives this a {pick.win_prob:.1f}% win probability, a {pick.edge_display} edge over the market"
    if pick.win_prob is not None:
        return f"model gives this a {pick.win_prob:.1f}% probability, a {pick.edge_display} edge against the line"
    return f"projection shows a {pick.edge_display} edge against the current line"


def generate_game_reasoning(ctx: GameContext, pick: MarketPick) -> str:
    """Builds one reasoning sentence for a game pick. Degrades gracefully."""
    picked_is_home = ctx.home.name in pick.team_or_side
    picked, other = (ctx.home, ctx.away) if picked_is_home else (ctx.away, ctx.home)

    clauses = [
        _clause_power_gap(picked, other),
        _clause_streak(picked),
        _clause_last10(picked),
        _clause_sos(picked, other),
        _clause_efficiency(picked, other),
    ]
    clauses = [c for c in clauses if c]

    edge_clause = _clause_edge(pick)

    if not clauses:
        return f"{pick.team_or_side}: {edge_clause}."

    body = "; ".join(clauses)
    return f"{pick.team_or_side}: {body}; {edge_clause}."


if __name__ == "__main__":
    home = TeamContext(name="Las Vegas Aces", power_score=91.2, win_percentage=0.8,
                        last_10_record="8-2", streak_type="win", streak_length=3,
                        schedule_difficulty=12.4, efficiency_score=72.0, efficiency_is_real=True)
    away = TeamContext(name="Chicago Sky", power_score=63.5, win_percentage=0.3,
                        last_10_record="3-7", streak_type="loss", streak_length=2,
                        schedule_difficulty=-4.2, efficiency_score=35.0, efficiency_is_real=True)

    ctx = GameContext(sport="wnba", home=home, away=away)

    pick = MarketPick(
        market="moneyline", team_or_side="Las Vegas Aces ML", win_prob=64.0,
        edge_value=12.3, edge_display="+12.3%", odds=-175, projected="82.1-74.6",
    )
    print(generate_game_reasoning(ctx, pick))
