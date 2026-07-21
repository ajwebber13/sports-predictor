"""
daily_alert.py

The new consolidated daily Telegram alert. Replaces the existing per-sport
alert scripts (wnba_slate_digest.py-style outputs, MLB alerts) with one
leaner format:

    - Only games clearing an edge threshold on ML/Spread/Total (up to 2
      markets per game, via game_pick_selector.py)
    - AI reasoning per game pick (via ai_game_analyzer.py)
    - A "Best Guaranteed" prop spotlight (top 1-2 highest-confidence props
      of the day, reusing Edge Finder + AI Prop Analyzer)

Everything else (full dashboard, all-props table, full game board) stays
exactly as-is. This script only changes what gets SENT to Telegram.

WIRING NOTES:
- Replace the three `fetch_*` functions with your real calls:
    fetch_raw_games()        -> however you currently pull /​<sport>/edges
    fetch_game_contexts()    -> power_score/elo/form/sos/defense per team
    fetch_best_props()       -> edge_finder.get_edge_finder(), tightened
- `send_telegram()` should reuse whatever bot/channel setup you already
  have in telegram_alerts.py / wnba_props_alert.py (bot token, chat id).
  Left as a stub here so you can drop in your existing sender.
"""

import sys
from datetime import date

from game_pick_selector import get_daily_game_picks, MarketPick
from ai_game_analyzer import GameContext, TeamContext, generate_game_reasoning

# If ai_prop_analyzer.py and edge_finder.py already exist in your repo,
# import them directly instead of re-implementing anything here.
try:
    from edge_finder import get_edge_finder
    from ai_prop_analyzer import generate_prop_reasoning  # adjust name if different
    HAVE_PROP_MODULES = True
except ImportError:
    HAVE_PROP_MODULES = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SPORTS_LIVE = ["wnba", "mlb"]          # per Drew: these two first
BEST_PROP_MIN_EDGE_SCORE = 85          # tighter than the existing 80 floor
BEST_PROP_MAX_COUNT = 2                # spotlight, not a list


# ---------------------------------------------------------------------------
# Data fetch layer — replace stubs with real calls
# ---------------------------------------------------------------------------

def fetch_raw_games(sport: str) -> list[dict]:
    """
    STUB — replace with your real fetch, e.g.:
        resp = requests.get(f"{API_BASE}/{sport}/edges")
        return resp.json()
    """
    raise NotImplementedError("Wire this up to your real /​<sport>/edges call")


def fetch_game_contexts(sport: str, raw_games: list[dict]) -> dict[str, GameContext]:
    """
    STUB — build one GameContext per game/market combo, keyed the same way
    ai_game_analyzer.annotate_daily_picks() expects: "GameLabel:market".
    Pull power_score/elo/form/sos/defense_factor from ranking_engine.py /
    elo_ratings.py / team_form_engine.py / strength_of_schedule.py the same
    way your dashboard or power_rankings.py already does.
    """
    raise NotImplementedError("Wire this up to your real ranking/context data")


def fetch_best_props(sport: str) -> list[dict]:
    """
    Uses Edge Finder if available. Tightens the existing confidence floor
    so only the day's strongest 1-2 props get spotlighted, instead of the
    full qualifying list.
    """
    if not HAVE_PROP_MODULES:
        return []

    all_edges = get_edge_finder(sport=sport, date=str(date.today()), top_n=20)
    strong = [p for p in all_edges if p.get("edge_score", 0) >= BEST_PROP_MIN_EDGE_SCORE]
    strong.sort(key=lambda p: p.get("edge_score", 0), reverse=True)
    return strong[:BEST_PROP_MAX_COUNT]


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------

MARKET_EMOJI = {"moneyline": "🎯", "spread": "📏", "total": "🔢"}
SPORT_EMOJI = {"wnba": "🏀", "mlb": "⚾", "nba": "🏀", "nfl": "🏈", "cfb": "🏈"}


def format_pick_block(pick: MarketPick, reasoning: str | None) -> str:
    emoji = MARKET_EMOJI.get(pick.market, "•")
    odds_str = f" ({pick.odds})" if pick.odds else ""
    lines = [f"{emoji} {pick.market.title()}: {pick.team_or_side}{odds_str} — {pick.edge_display}"]
    if reasoning:
        lines.append(f"   💡 {reasoning}")
    return "\n".join(lines)


def format_game_section(game: dict, contexts: dict[str, GameContext]) -> str:
    lines = [f"\n📌 {game['game']}"]
    for pick in game["picks"]:
        key = f"{game['game']}:{pick.market}"
        ctx = contexts.get(key)
        reasoning = generate_game_reasoning(ctx) if ctx else None
        lines.append(format_pick_block(pick, reasoning))
    return "\n".join(lines)


def format_prop_section(props: list[dict]) -> str:
    if not props:
        return ""
    lines = ["\n🔒 BEST GUARANTEED PROP" + ("S" if len(props) > 1 else "")]
    for p in props:
        reasoning = None
        if HAVE_PROP_MODULES:
            try:
                reasoning = generate_prop_reasoning(p)
            except Exception:
                reasoning = None
        line = f"⭐ {p.get('player_name', 'Unknown')} — {p.get('stat', '')} {p.get('pick_side', '')} {p.get('line', '')}"
        lines.append(line)
        if reasoning:
            lines.append(f"   💡 {reasoning}")
    return "\n".join(lines)


def build_daily_message(sport: str, daily_games: list[dict], contexts: dict, best_props: list[dict]) -> str:
    emoji = SPORT_EMOJI.get(sport, "🏆")
    header = f"{emoji} {sport.upper()} — {date.today().strftime('%b %d, %Y')} Best Bets"

    if not daily_games:
        game_section = "\nNo games cleared today's edge threshold — sitting this slate out."
    else:
        game_section = "".join(format_game_section(g, contexts) for g in daily_games)

    prop_section = format_prop_section(best_props)

    parts = [header, game_section]
    if prop_section:
        parts.append(prop_section)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Sender — replace with your real Telegram sender
# ---------------------------------------------------------------------------

def send_telegram(message: str, sport: str) -> None:
    """
    STUB — replace with your real send logic from telegram_alerts.py /
    wnba_props_alert.py (bot token + chat id + requests.post to the
    Telegram Bot API), including whatever dry-run flag pattern you use
    elsewhere (e.g. --dry-run to print instead of send).
    """
    print(f"--- Would send to Telegram ({sport}) ---")
    print(message)
    print("--- end message ---\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_daily_alert(sport: str, dry_run: bool = True) -> None:
    raw_games = fetch_raw_games(sport)
    daily_games = get_daily_game_picks(sport, raw_games)
    contexts = fetch_game_contexts(sport, raw_games)
    best_props = fetch_best_props(sport)

    message = build_daily_message(sport, daily_games, contexts, best_props)

    if dry_run:
        print(message)
    else:
        send_telegram(message, sport)


if __name__ == "__main__":
    dry_run = "--send" not in sys.argv
    sports = SPORTS_LIVE

    for s in sports:
        try:
            run_daily_alert(s, dry_run=dry_run)
        except NotImplementedError as e:
            print(f"[{s}] Not wired up yet: {e}")
