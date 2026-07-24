"""
telegram_alerts.py
===================
Sends game prediction alerts to Culture & Pulse Picks Telegram channel.
Sports: NFL, CFB, WNBA, NBA, College Basketball

Season gates prevent alerts during inactive periods.
Date filtering ensures only today's games (Central Time) are sent.
Game times pulled from ESPN (free, no API key needed).
Alert throttle caps picks per slate and removes correlated bets.
"""

import requests
import argparse
import os
import sys
import time
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from database import log_prediction
    LOGGING_ENABLED = True
except ImportError:
    LOGGING_ENABLED = False

# Fallback webhook — used when a sport has no dedicated channel yet
# (e.g. nba, ncaaw) or when get_webhook_for_sport() can't find an env
# var. Kept from the old content-type migration rather than removed,
# so nothing silently fails to send during the sport-channel rollout.
DISCORD_WEBHOOK_GAME_PICKS = os.getenv("DISCORD_WEBHOOK_GAME_PICKS", "")
API_BASE         = "https://sports-predictor-api-44a0.onrender.com"
CENTRAL_OFFSET   = -5  # CDT


# ─────────────────────────────────────────────────────────────
# ESPN SCHEDULE ENDPOINTS
# ─────────────────────────────────────────────────────────────

ESPN_SCHEDULE_ENDPOINTS = {
    "nfl":   "football/nfl",
    "ncaaf": "football/college-football",
    "nba":   "basketball/nba",
    "ncaab": "basketball/mens-college-basketball",
    "ncaaw": "basketball/womens-college-basketball",
    "wnba":  "basketball/wnba",
    "mlb":   "baseball/mlb",
}

SEASON_WINDOWS = {
    "nfl":   (9, 2),
    "ncaaf": (8, 1),
    "ncaab": (11, 4),
    "ncaaw": (11, 4),
    "wnba":  (5, 10),
    "nba":   (10, 5),
    "mlb":   (3, 10),   # spring training through World Series
}

def is_in_season(sport: str) -> bool:
    window = SEASON_WINDOWS.get(sport)
    if not window:
        return True
    start_month, end_month = window
    current_month = datetime.now().month
    if start_month <= end_month:
        return start_month <= current_month <= end_month
    else:
        return current_month >= start_month or current_month <= end_month


# ─────────────────────────────────────────────────────────────
# DATE HELPERS
# ─────────────────────────────────────────────────────────────

def get_today_ct() -> datetime.date:
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def is_today_ct(utc_str: str) -> bool:
    try:
        utc_dt     = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        return central_dt.date() == get_today_ct()
    except:
        return True


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def format_game_time(utc_str: str) -> str:
    try:
        utc_dt     = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        central_dt = utc_dt + timedelta(hours=CENTRAL_OFFSET)
        day        = central_dt.strftime("%a %b ")
        day       += str(central_dt.day)
        t          = central_dt.strftime(" · %I:%M %p CT")
        return day + t
    except:
        return "Time TBD"


def get_game_times(sport: str) -> tuple:
    endpoint = ESPN_SCHEDULE_ENDPOINTS.get(sport)
    if not endpoint:
        return {}, {}

    url = f"http://site.api.espn.com/apis/site/v2/sports/{endpoint}/scoreboard"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"ESPN game times error ({sport}): {e}")
        return {}, {}

    times     = {}
    times_raw = {}

    for event in data.get("events", []):
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp        = competitions[0]
        competitors = comp.get("competitors", [])
        home_team   = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), "")
        away_team   = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), "")
        utc_time    = event.get("date", "")
        fmt         = format_game_time(utc_time) if utc_time else "Time TBD"

        for key in [f"{away_team} @ {home_team}", f"{home_team} @ {away_team}", home_team, away_team]:
            times[key]     = fmt
            times_raw[key] = utc_time

    print(f"ESPN returned {len(data.get('events', []))} events for {sport}")
    return times, times_raw


def _webhook_for(sport: str) -> str:
    """Routes to the sport's own Discord channel, added 2026-07-23 —
    Discord is now organized per sport instead of by content type.
    'ncaaf' is mapped to 'cfb' since that's this file's internal key
    for college football, but the actual channel/env var is
    DISCORD_WEBHOOK_CFB. Falls back to the old DISCORD_WEBHOOK_GAME_PICKS
    constant for any sport without its own channel yet (nba, ncaaw) or
    if the sport-specific env var isn't set — never silently drops a
    message just because a channel doesn't exist yet."""
    from discord_alerts import get_webhook_for_sport
    sport_key = "cfb" if sport == "ncaaf" else sport
    return get_webhook_for_sport(sport_key) or DISCORD_WEBHOOK_GAME_PICKS


def send_message(text: str, sport: str = None):
    from discord_alerts import send_discord_message, html_to_discord_markdown
    webhook = _webhook_for(sport) if sport else DISCORD_WEBHOOK_GAME_PICKS
    send_discord_message(html_to_discord_markdown(text), webhook_url=webhook)

def sport_emoji(sport: str) -> str:
    return "🏈" if sport in ["ncaaf", "nfl"] else "⚾" if sport == "mlb" else "🏀"


def sport_label(sport: str) -> str:
    labels = {
        "ncaaf": "College Football",
        "nfl":   "NFL",
        "ncaab": "College Basketball (Men)",
        "ncaaw": "College Basketball (Women)",
        "wnba":  "WNBA",
        "nba":   "NBA",
        "mlb":   "MLB",
    }
    return labels.get(sport, sport.upper())


def edge_label(edge_pct: float) -> str:
    if edge_pct >= 10: return "★★★ STRONG EDGE"
    if edge_pct >= 6:  return "★★  MODERATE EDGE"
    return "★   SLIGHT EDGE"


def get_recommended_prob(bet: dict) -> float:
    """
    Returns the model's confidence in the PICKED side actually hitting
    — the picked team winning (moneyline), covering (spread), or the
    total landing the right direction (Over/Under).

    FIXED (2026-07-20): this used to assume model_prob was always the
    HOME team's win probability, and flipped it (100 - model_prob)
    whenever the picked team's name wasn't found in bet_label. That
    was already wrong for moneyline the moment routes_wnba.py (and
    since then routes_mlb.py/routes_cfb.py/routes_nfl.py) started
    setting model_prob to whichever side the model actually
    recommends — home OR away, not home-only. An away-team pick with
    real 64% confidence was being read as 36% here, which could wrongly
    filter out strong picks (or let weak ones through) at the
    confidence gate in render_job.py. It's also flatly wrong for
    spread/total bets, which don't have a home/away team to match
    against at all (bet_label is "Team +1.5" or "Over 8.5" — cover/
    total probability, not a win probability to flip).

    Every route this now reads from already computes model_prob as
    the confidence in the actual recommended pick, for every market —
    no home/away logic needed here anymore. Trust it directly.
    """
    return round(float(bet.get("model_prob", 50)), 1)


def fmt_odds(odds) -> str:
    if odds is None:
        return ""
    try:
        odds = int(odds)
        return f"+{odds}" if odds > 0 else str(odds)
    except:
        return ""


def get_raw_time_for_bet(bet: dict, times_raw: dict) -> str:
    game  = bet.get("game", "")
    parts = game.split(" @ ")
    for key in [game] + parts:
        raw = times_raw.get(key)
        if raw:
            return raw
    return ""


# ─────────────────────────────────────────────────────────────
# FORMATTERS
# ─────────────────────────────────────────────────────────────

def format_header(bets: list, sport: str) -> str:
    emoji    = sport_emoji(sport)
    label    = sport_label(sport)
    top_edge = max((b.get("edge", 0) * 100 for b in bets), default=0)
    today    = get_today_ct().strftime("%B %d, %Y")
    return (
        f"{emoji} <b>Culture &amp; Pulse Picks</b>\n"
        f"📅 {today} — {label}\n"
        f"<b>Edges found:</b> {len(bets)}  |  <b>Top edge:</b> +{round(top_edge, 1)}%\n\n"
        f"Full slate below 👇"
    )


def format_slate_summary(bets: list, sport: str, suppressed: list = None) -> str:
    emoji = sport_emoji(sport)
    label = sport_label(sport)
    today = get_today_ct().strftime("%B %d, %Y")

    lines = [
        f"{emoji} <b>Culture &amp; Pulse Picks</b>",
        f"📅 {today} — {label} Slate\n",
    ]

    if bets:
        for b in sorted(bets, key=lambda x: x.get("edge", 0), reverse=True):
            game      = b.get("game", "")
            bet_label = b.get("bet", "")
            edge_pct  = round(b.get("edge", 0) * 100, 1)
            stars     = "★★★" if edge_pct >= 15 else "★★" if edge_pct >= 8 else "★"
            lines.append(f"✅ {game}")
            lines.append(f"   {bet_label} | Edge +{edge_pct}% {stars}\n")
    else:
        lines.append("No qualifying edges found today.\n")

    if suppressed:
        try:
            from alert_throttle import format_throttle_summary
            lines.append(format_throttle_summary(bets, suppressed, sport))
        except Exception:
            lines.append(f"<i>{len(suppressed)} pick(s) filtered by throttle</i>")

    lines.append("\nFull breakdown for each pick coming up 👇")
    return "\n".join(lines)


def format_alert(bet: dict, sport: str, game_time: str) -> str:
    emoji      = sport_emoji(sport)
    label      = sport_label(sport)
    game       = bet.get("game", "")
    bet_label  = bet.get("bet", "")
    odds       = bet.get("odds")
    edge_pct   = round(bet.get("edge", 0) * 100, 1)
    model_prob = bet.get("model_prob", 0)
    implied    = bet.get("implied_prob", 0)
    projected  = bet.get("projected")

    home_record   = bet.get("home_record", "")
    away_record   = bet.get("away_record", "")
    home_rest     = bet.get("home_rest")
    away_rest     = bet.get("away_rest")
    home_injuries = bet.get("home_injuries", "")
    away_injuries = bet.get("away_injuries", "")

    parts       = game.split(" @ ")
    away_team   = parts[0] if len(parts) == 2 else ""
    home_team   = parts[1] if len(parts) == 2 else ""
    home_prob = round(float(model_prob), 1)
    away_prob = round(100 - home_prob, 1)

    odds_str  = f" ({fmt_odds(odds)})" if odds else ""
    proj_line = f"\n📊 <b>Projected:</b> {projected}" if projected else ""

    rec_parts = []
    if away_record:
        rec_parts.append(f"{away_team}: {away_record}")
    if home_record:
        rec_parts.append(f"{home_team}: {home_record}")
    records_line = "\n📋 <b>Records:</b> " + " | ".join(rec_parts) if rec_parts else ""

    rest_parts = []
    if away_rest is not None:
        rest_parts.append(f"{away_team}: {away_rest}d rest")
    if home_rest is not None:
        rest_parts.append(f"{home_team}: {home_rest}d rest")
    rest_line = "\n💤 <b>Rest:</b> " + " | ".join(rest_parts) if rest_parts else ""

    inj_lines = ""
    if home_injuries:
        inj_lines += f"\n🚑 <b>{home_team} Out/Doubtful:</b> {home_injuries}"
    if away_injuries:
        inj_lines += f"\n🚑 <b>{away_team} Out/Doubtful:</b> {away_injuries}"

    try:
        from clv_tracker import log_pick
        bet_team = bet_label.replace(" ML", "").strip()
        log_pick(
            sport      = sport,
            home_team  = home_team,
            away_team  = away_team,
            bet_team   = bet_team,
            model_prob = model_prob,
            edge       = edge_pct,
        )
    except Exception:
        pass

    return (
        f"{emoji} <b>{label} — PICK ALERT</b>\n\n"
        f"<b>{game}</b>\n"
        f"🕐 {game_time}\n\n"
        f"✅ <b>Pick:</b> {bet_label}{odds_str}\n"
        f"📈 <b>Edge:</b> +{edge_pct}% — {edge_label(edge_pct)}\n"
        f"{proj_line}\n\n"
        f"<b>WIN PROBABILITY</b>\n"
        f"{away_team}: {away_prob}%\n"
        f"{home_team}: {home_prob}%\n"
        f"Market: {implied}%\n"
        f"{records_line}"
        f"{rest_line}"
        f"{inj_lines}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Culture & Pulse Analytics</i>\n"
        f"<i>For entertainment only. Bet responsibly.</i>"
    )


def format_no_games(sport: str) -> str:
    emoji = sport_emoji(sport)
    label = sport_label(sport)
    today = get_today_ct().strftime("%B %d, %Y")
    return (
        f"{emoji} <b>Culture &amp; Pulse Picks — {label}</b>\n\n"
        f"📅 {today}\n"
        f"No {label} games scheduled today."
    )


# ─────────────────────────────────────────────────────────────
# API ROUTING
# ─────────────────────────────────────────────────────────────

def get_edges_url(sport: str, simulations: int) -> str:
    endpoints = {
        "nfl":   f"{API_BASE}/nfl/edges",
        "ncaaf": f"{API_BASE}/ncaaf/edges",
        "ncaab": f"{API_BASE}/ncaab/edges",
        "ncaaw": f"{API_BASE}/ncaaw/edges",
        "wnba":  f"{API_BASE}/wnba/edges",
        "nba":   f"{API_BASE}/nba/edges",
        "mlb":   f"{API_BASE}/mlb/edges",
    }
    url = endpoints.get(sport)
    if not url:
        raise ValueError(f"Unknown sport: {sport}")
    return url


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run_alerts(sport: str = "ncaaf", simulations: int = 10000):
    emoji       = sport_emoji(sport)
    label       = sport_label(sport)
    today_label = get_today_ct().strftime("%B %d, %Y")

    if not is_in_season(sport):
        print(f"{label} is not in season. Skipping.")
        return

    # ── SLATE DIGEST (WNBA only) — fires before edge alerts ──
    if sport == "wnba":
        try:
            from wnba_slate_digest import run_digest
            print("Running WNBA slate digest...")
            run_digest(dry_run=False)
            time.sleep(2)
        except Exception as e:
            print(f"Slate digest error (non-fatal): {e}")

    print(f"Fetching edges for {sport}...")
    game_times, game_times_raw = get_game_times(sport)
    print(f"Game times loaded: {len(game_times)} entries")

    try:
        url  = get_edges_url(sport, simulations)
        r    = requests.get(url, params={"simulations": simulations}, timeout=60)
        data = r.json()
    except Exception as e:
        print(f"Could not reach API: {e}")
        return

    bets_raw = data.get("best_bets", [])

    # ── DATE FILTER ──
    bets = []
    for bet in bets_raw:
        raw_time = get_raw_time_for_bet(bet, game_times_raw)
        if raw_time and not is_today_ct(raw_time):
            print(f"Skipping stale game (not today): {bet.get('game')} — {raw_time}")
            continue
        bets.append(bet)

    if not bets:
        print(f"No {label} games today ({today_label}).")
        # WNBA slate digest (above) already sends its own "no games" message —
        # skip the duplicate here.
        if sport != "wnba":
            send_message(format_no_games(sport), sport)
        return

    if LOGGING_ENABLED:
        for bet in bets:
            try:
                log_prediction(bet, sport, market=bet.get("market", "moneyline"))
            except Exception as e:
                print(f"DB prediction save failed: {e}")

    # ── THROTTLE: edge filter + correlation filter + slate cap ──
    try:
        from alert_throttle import throttle_bets
        clean_bets, suppressed, throttle_log = throttle_bets(bets, sport)
        print(throttle_log)
    except Exception as e:
        print(f"Throttle error — falling back to confidence filter: {e}")
        # Fallback to basic confidence filter if throttle fails
        clean_bets = []
        suppressed = []
        for bet in bets:
            if get_recommended_prob(bet) >= 57:
                clean_bets.append(bet)
            else:
                suppressed.append(bet)

    # ── WNBA: digest already sent edge picks inline — skip duplicate summary/alerts ──
    if sport == "wnba":
        if clean_bets:
            print(f"WNBA: {len(clean_bets)} edge(s) already included in slate digest. No duplicate alerts sent.")
        else:
            print("WNBA: No clean edges — slate digest already handled game-level output. No summary sent.")
        return

    if not clean_bets:
        print("All alerts filtered. Nothing sent.")
        send_message(
            f"{emoji} <b>C&amp;P Picks — {label}</b>\n\n"
            f"📅 {today_label}\n"
            f"No clean edges after model validation. Stay patient.",
            sport,
        )
        return

    # ── SEND SLATE SUMMARY ──
    send_message(format_slate_summary(clean_bets, sport, suppressed=suppressed), sport)
    time.sleep(1)

    # ── SEND INDIVIDUAL ALERTS ──
    for bet in clean_bets:
        game      = bet.get("game", "")
        game_time = game_times.get(game, "Time TBD")

        if game_time == "Time TBD":
            parts = game.split(" @ ")
            if len(parts) == 2:
                game_time = game_times.get(parts[0], game_times.get(parts[1], "Time TBD"))

        msg = format_alert(bet, sport, game_time)
        send_message(msg, sport)
        time.sleep(1)

    print(f"Sent {len(clean_bets)} alerts for {label} on {today_label} to Discord ({sport}'s channel)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", default="ncaaf")
    parser.add_argument("--sims", type=int, default=10000)
    args = parser.parse_args()
    run_alerts(sport=args.sport, simulations=args.sims)


def format_game_card(bet: dict, sport: str, game_time: str) -> str:
    """
    PREDICTION ENGINE v2 (2026-07-20): now market-aware. Previously this
    always tried to derive a "winner" team + win% from home_win_prob/
    away_win_prob (or model_prob as a fallback), then showed that as the
    Pick line — that only makes sense for moneyline. Spread bets kinda
    worked by accident (bet_label starts with a team name, so the old
    team-matching logic still found the right team), but Total bets
    (bet_label like "Over 8.5") never matched either team name and fell
    through to showing a team name + win% on the Pick line where "Over
    8.5 (-105)" should have been — completely wrong content on screen.
    Spread/total bets also don't carry home_win_prob/away_win_prob at
    all (only moneyline bets do — see routes_wnba.py/routes_mlb.py/
    routes_cfb.py/routes_nfl.py), so model_prob there is the cover/total
    probability itself, not a value to run through home/away logic.

    Moneyline formatting below is UNCHANGED from before this fix.
    Spread/total now use their own simpler branch: show the pick and
    its real probability directly, skip the home/away win-prob
    breakdown line (it doesn't describe a spread/total pick).
    """
    emoji     = sport_emoji(sport)
    game      = bet.get("game", "")
    bet_label = bet.get("bet", "")
    odds      = bet.get("odds")
    projected = bet.get("projected")
    market    = bet.get("market", "moneyline")

    home_record   = bet.get("home_record", "")
    away_record   = bet.get("away_record", "")
    home_rest     = bet.get("home_rest")
    away_rest     = bet.get("away_rest")
    home_injuries = bet.get("home_injuries", "")
    away_injuries = bet.get("away_injuries", "")

    parts     = game.split(" @ ")
    away_team = parts[0] if len(parts) == 2 else ""
    home_team = parts[1] if len(parts) == 2 else ""

    lines = [f"{emoji} <b>{game}</b>", f"🕐 {game_time}"]

    context_lines = []
    rec = []
    if away_record: rec.append(f"{away_team.split()[-1]} {away_record}")
    if home_record: rec.append(f"{home_team.split()[-1]} {home_record}")
    if rec: context_lines.append("📋 " + " | ".join(rec))

    rest = []
    if away_rest is not None: rest.append(f"{away_team.split()[-1]}: {away_rest}d rest")
    if home_rest is not None: rest.append(f"{home_team.split()[-1]}: {home_rest}d rest")
    if rest: context_lines.append("🔥 " + " | ".join(rest))

    if away_injuries: context_lines.append(f"🚑 {away_team.split()[-1]}: {away_injuries}")
    if home_injuries: context_lines.append(f"🚑 {home_team.split()[-1]}: {home_injuries}")

    if context_lines:
        lines.append("───────────────────")
        lines.extend(context_lines)

    has_edge = bool(bet_label)
    odds_str = f" ({fmt_odds(odds)})" if odds else ""

    if market in ("spread", "total"):
        # Spread/total: bet_label already fully describes the pick
        # ("Las Vegas Aces -6.5" / "Over 158.5") and model_prob IS the
        # real probability of that exact outcome — no team/win-prob
        # derivation needed or wanted here.
        pick_prob = round(float(bet.get("model_prob", 0)), 1)
        lines.append("───────────────────")
        if has_edge:
            lines.append(f"✅ <b>Pick: {bet_label} ({pick_prob}%)</b>{odds_str}")
        else:
            lines.append("🔴 No edge pick")
        if projected:
            lines.append(f"📐 Projected: {projected}")
        lines.append("")
        lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
        return "\n".join(lines)

    # ── Moneyline — unchanged from before this fix ──
    # home_win_prob/away_win_prob are explicit, unambiguous fields the
    # API now provides directly. model_prob (still present for backward
    # compat) is NOT always the home team's probability — it's
    # whichever team the model's edge favors, home or away, which
    # caused a real mislabeling bug when the recommended team was the
    # away team: this code used to assume model_prob == home_prob
    # unconditionally, silently corrupting the win-probability split
    # (and the "Pick" line, in some cases) whenever the away team was
    # actually the one being recommended. Falls back to the old
    # (buggy but functional) derivation only if the API response is
    # from before this fix and doesn't have the new fields yet.
    if "home_win_prob" in bet and "away_win_prob" in bet:
        home_prob = round(float(bet["home_win_prob"]), 1)
        away_prob = round(float(bet["away_win_prob"]), 1)
    else:
        model_prob = bet.get("model_prob", 50)
        home_prob  = round(float(model_prob), 1)
        away_prob  = round(100 - home_prob, 1)

    winner      = home_team if home_prob > away_prob else away_team
    winner_prob = max(home_prob, away_prob)

    # When there IS an edge pick, bet_label already unambiguously names
    # the recommended team (it's how the API decided which team to
    # recommend in the first place) — trust it directly instead of
    # re-deriving "winner" from a probability comparison, which can
    # legitimately disagree with bet_label. A value bet on an underdog
    # (model favors Team A outright, but Team B is undervalued by the
    # market) is exactly the case where "highest win probability" and
    # "the actual recommended bet" are different teams — re-deriving
    # winner from probability alone would then show the WRONG team
    # next to a real edge pick.
    if has_edge:
        pick_team = bet_label.rsplit(" ML", 1)[0].strip()
        if pick_team == home_team:
            winner, winner_prob = home_team, home_prob
        elif pick_team == away_team:
            winner, winner_prob = away_team, away_prob
        # else: unrecognized label format — fall back to the
        # probability-derived winner above rather than showing a
        # blank/wrong team.

    lines.append("───────────────────")
    lines.append(f"📊 {away_team.split()[-1]} {away_prob}% · {home_team.split()[-1]} {home_prob}%")

    if has_edge:
        lines.append(f"✅ <b>Pick: {winner} ({winner_prob}%)</b>{odds_str}")
    else:
        lines.append(f"🤖 Model: {winner} ({winner_prob}%)")
        lines.append("🔴 No edge pick")

    if projected:
        lines.append(f"📐 Projected: {projected}")

    lines.append("")
    lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
    return "\n".join(lines)
