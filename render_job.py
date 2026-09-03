"""
render_job.py — Culture & Pulse Analytics
Runs on Render cron schedule daily.
Fires alerts for all active sports based on season gates.
No PC required — runs entirely in the cloud.

Flags:
  --sport wnba       Run one specific sport only
  --exclude wnba     Run all sports except the specified one
  --retry            Noon retry run for missed morning picks
"""

import os
import sys
import requests
import time
import argparse
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

API_BASE         = "https://sports-predictor-api-44a0.onrender.com"
# Fallback webhook, kept from the old content-type migration — used
# only for a sport with no dedicated channel yet, or when no sport
# context is available at all (shouldn't normally happen).
DISCORD_WEBHOOK_GAME_PICKS = os.getenv("DISCORD_WEBHOOK_GAME_PICKS", "")

ALL_SPORTS = ["wnba", "nfl", "cfb"]  # nba, ncaab, mlb temporarily disabled

SPORT_ENDPOINTS = {
    "nba":   f"{API_BASE}/nba/edges",
    "wnba":  f"{API_BASE}/wnba/edges",
    "nfl":   f"{API_BASE}/nfl/edges",
    "cfb":   f"{API_BASE}/cfb/edges",
    "ncaab": f"{API_BASE}/ncaab/edges",
    "mlb":   f"{API_BASE}/mlb/edges",
}

# nba has no dedicated predictor module yet (no routes_nba.py either) —
# nothing to check for it here.
SPORT_PREDICTOR_MODULES = {
    "wnba":  "wnba_predictor",
    "nfl":   "nfl_predictor",
    "cfb":   "cfb_predictor",
    "ncaab": "ncaab_predictor",
    "mlb":   "mlb_predictor",
}


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{ts}] {msg}", flush=True)


def wake_api():
    """Ping the API to wake Render free tier before running alerts."""
    log("Waking API...")
    try:
        requests.get(f"{API_BASE}/", timeout=60)
        time.sleep(10)
        log("API awake.")
    except Exception as e:
        log(f"Wake ping failed: {e}")


def check_predictor_imports():
    """Import every sport's predictor module and warn that sport's
    Discord channel if the import fails. Added 2026-09-02 after
    nfl_predictor.py was silently reduced to a single stray character
    by commit 073e8c3 and stayed that way for weeks — /nfl/edges 500'd
    on every call, but nothing surfaced it because the failure happened
    on the API service, not here. Runs against this same repo checkout
    (render_job.py and the API service deploy from the same code), so
    a wiped/corrupted predictor file gets caught here even for a sport
    that isn't in this run's `sports` list."""
    import importlib
    for sport, module_name in SPORT_PREDICTOR_MODULES.items():
        try:
            importlib.import_module(module_name)
        except Exception as e:
            log(f"STARTUP CHECK FAILED: {module_name}.py ({sport}) — {e}")
            send_discord_alert(
                f"⚠️ <b>{sport.upper()} predictor import failed</b>\n"
                f"<code>{module_name}.py</code>: {e}\n"
                f"{sport.upper()} edges will not run until this is fixed.",
                sport,
            )


def send_discord_alert(text: str, sport: str = None) -> bool:
    """Routed to the given sport's own Discord channel, added
    2026-07-23 — Discord is now organized per sport instead of by
    content type. Falls back to the old DISCORD_WEBHOOK_GAME_PICKS
    constant if sport is None or has no dedicated channel/env var yet
    — never silently drops a message just because a channel doesn't
    exist. Returns True only if the message actually reached Discord
    — callers must check this instead of assuming success, so a
    failed send doesn't get logged as 'Sent' (2026-07-24 fix)."""
    try:
        from discord_alerts import send_discord_message, html_to_discord_markdown, get_webhook_for_sport
        webhook = (get_webhook_for_sport(sport) if sport else "") or DISCORD_WEBHOOK_GAME_PICKS
        if not webhook:
            log("No Discord webhook — skipping.")
            return False
        ok = send_discord_message(html_to_discord_markdown(text), webhook_url=webhook)
        if not ok:
            log("Discord send failed — see error above.")
        return ok
    except Exception as e:
        log(f"Discord exception: {e}")
        return False


def fetch_edges_with_retry(sport: str, attempts: int = 3, backoff: int = 15):
    """Fetch a sport's /edges endpoint with retries on transient
    network errors (timeouts, connection resets, etc). Returns the
    parsed JSON dict on success. Returns None if every attempt fails
    — and sends a Discord alert to the sport's channel so a real API
    outage doesn't look identical to 'no edges today' (silence)."""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            r = requests.get(SPORT_ENDPOINTS[sport], timeout=280)
            return r.json()
        except Exception as e:
            last_error = e
            log(f"API error for {sport} (attempt {attempt}/{attempts}): {e}")
            if attempt < attempts:
                time.sleep(backoff)

    log(f"API fetch failed for {sport} after {attempts} attempts — giving up.")
    send_discord_alert(
        f"⚠️ <b>{sport.upper()} fetch failed</b>\n"
        f"Could not reach the edges API after {attempts} attempts.\n"
        f"Error: {last_error}",
        sport,
    )
    return None


# ─────────────────────────────────────────────────────────────
# DEDUP CHECK — prevents noon retry from re-alerting a game
# already covered by the morning alert.
#
# Matches database.py's actual schema: get_conn(), table
# "predictions", columns date / sport / game / market.
#
# PREDICTION ENGINE v2 (2026-07-20): now checks per (sport, game,
# market) instead of per (sport, game). Before this fix, a game that
# already had a moneyline pick logged this morning would read as
# "already alerted" even if the noon retry found a brand-new spread
# or total edge for that same game that was never sent — the retry
# would skip it entirely, silently. market is optional (defaults to
# None -> checks ALL markets for the game, old behavior) so any
# caller not yet passing a market keeps working unchanged.
# ─────────────────────────────────────────────────────────────

def already_alerted_today(sport: str, game: str, market: str = None) -> bool:
    """
    Returns True if a pick for this game (and, if given, this specific
    market) was already logged today (e.g. by the morning alert run).
    """
    try:
        from database import get_conn
        today = datetime.now().strftime("%Y-%m-%d")
        conn  = get_conn()
        if market:
            cur = conn.execute(
                "SELECT COUNT(*) as cnt FROM predictions "
                "WHERE sport = ? AND game = ? AND date = ? AND market = ?",
                (sport, game, today, market),
            )
        else:
            cur = conn.execute(
                "SELECT COUNT(*) as cnt FROM predictions "
                "WHERE sport = ? AND game = ? AND date = ?",
                (sport, game, today),
            )
        row = cur.fetchone()
        conn.close()
        return (row["cnt"] if row else 0) > 0
    except Exception as e:
        log(f"Dedup check failed ({e}) — defaulting to NOT alerting to avoid duplicates.")
        return True


# ─────────────────────────────────────────────────────────────
# ALERT RUNNER
# ─────────────────────────────────────────────────────────────

def run_alerts(sport: str, skip_if_already_alerted: bool = False) -> bool:
    log(f"Fetching {sport.upper()} edges...")

    # 280s inner timeout (was 150s, originally 60s) — 2026-07-22: real
    # timing data confirmed MLB's /edges route now reliably COMPLETES
    # (no longer crashes — that was a separate H2H caching bug, since
    # fixed) but takes up to ~254s on a congested run even after
    # weather/team-stats caching and MLB_EDGES_MAX_WORKERS lowered to
    # 3. If scheduled runs still time out at 280s, the fix is further
    # concurrency tuning in routes_mlb.py, not another blind timeout
    # bump. fetch_edges_with_retry() wraps this in 3 attempts and
    # alerts Discord if every attempt fails (2026-07-24 fix).
    data = fetch_edges_with_retry(sport)
    if data is None:
        return False

    bets = data.get("best_bets", [])

    # Auto-log today's odds to database
    try:
        from services.odds_parser import get_live_odds
        from database import log_odds, log_injuries, log_situational_factors

        if sport == "mlb":
            from mlb_data import get_mlb_events
            mlb_events = get_mlb_events()
            games = []
            for event in mlb_events:
                competitors = event["competitions"][0]["competitors"]
                home = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "home")
                away = next(c["team"]["displayName"] for c in competitors if c["homeAway"] == "away")
                games.append({"home_team": home, "away_team": away})
        else:
            games = get_live_odds(sport)

        log_odds(sport, games, source="odds_api" if games else "espn")
        log(f"Odds logged for {sport}")

        if sport == "wnba":
            try:
                from wnba_player_stats import update_recent
                update_recent(days=2)
                log("WNBA player stats updated")
            except Exception as e:
                log(f"WNBA player stats error: {e}")

        if sport == "mlb":
            try:
                from mlb_player_stats import update_recent
                update_recent(days=2)
                log("MLB player stats updated")
            except Exception as e:
                log(f"MLB player stats error: {e}")

        log_situational_factors(sport, games)
        log(f"Situational factors logged for {sport}")
    except Exception as e:
        log(f"Odds logging error: {e}")

    if not bets:
        log(f"No {sport.upper()} edges found today.")
        return False

    # ── LEANER CONSOLIDATED ALERT (WNBA/MLB per Drew's 2026-07-19 spec) ──
    # Groups by game, evaluates ML/spread/total, shows up to 2 qualifying
    # markets per game ranked by edge, adds AI reasoning, sends ONE
    # message instead of one-per-bet.
    #
    # NOTE (2026-07-20): MLB's /mlb/edges route now returns real
    # spread/total bets (Prediction Engine v2 — see routes_mlb.py), but
    # game_pick_selector.py's get_daily_game_picks() was documented as
    # treating MLB as moneyline-only. Until that file is updated to
    # match, MLB spread/total bets may be silently dropped or ignored by
    # this path even though they're present in `bets` below and get
    # logged to the database correctly either way (the log_prediction
    # loop right below runs on every bet in a qualifying game, not just
    # what game_pick_selector chose to display).
    if sport in ("wnba", "mlb"):
        try:
            from game_pick_selector import get_daily_game_picks
            from ai_game_analyzer import build_game_context, generate_game_reasoning
            from telegram_alerts import get_game_times, get_raw_time_for_bet, is_today_ct

            game_times, game_times_raw = get_game_times(sport)

            # date filter still applies before grouping
            todays_bets = []
            for bet in bets:
                raw_time = get_raw_time_for_bet(bet, game_times_raw)
                if raw_time and not is_today_ct(raw_time):
                    log(f"Skipping stale game: {bet.get('game')} — {raw_time}")
                    continue
                todays_bets.append(bet)

            if not todays_bets:
                log(f"No {sport.upper()} games today after date filter.")
                return False

            daily_games = get_daily_game_picks(sport, todays_bets)

            if skip_if_already_alerted:
                # NOTE: this still checks per-game only (no market arg),
                # since daily_games is grouped by game, not by market —
                # matches this function's existing granularity. The fix
                # below (per-bet, in the log_prediction loop) is what
                # actually prevents a specific market from being silently
                # skipped on retry; this game-level filter only decides
                # whether to re-render the Discord message for a game
                # that's already fully covered.
                daily_games = [
                    g for g in daily_games
                    if not already_alerted_today(sport, g["game"])
                ]

            if not daily_games:
                log(f"No {sport.upper()} games cleared today's edge threshold.")
                return False

            # log predictions for every underlying bet row that fed a
            # qualifying game (preserves existing prediction-logging
            # behavior). Each bet is checked individually against the
            # dedup table by its OWN market now, not just by game — so a
            # game that already has a moneyline row logged this morning
            # can still pick up a brand-new spread/total row on retry
            # instead of being skipped wholesale.
            qualifying_game_labels = {g["game"] for g in daily_games}
            for bet in todays_bets:
                if bet.get("game") not in qualifying_game_labels:
                    continue
                bet_market = bet.get("market", "moneyline")
                if skip_if_already_alerted and already_alerted_today(sport, bet.get("game", ""), market=bet_market):
                    log(f"Already alerted today, skipping duplicate: {bet.get('game')} [{bet_market}]")
                    continue
                try:
                    from database import log_prediction
                    log_prediction(bet, sport, market=bet_market)
                except Exception as e:
                    log(f"Prediction log error: {e}")

            rankings_by_team = {}
            try:
                from ranking_engine import get_rankings
                rankings_by_team = {r["team"]: r for r in get_rankings(sport)}
            except Exception as e:
                log(f"Rankings fetch failed (reasoning will degrade): {e}")

            emoji = "⚾" if sport == "mlb" else "🏀"
            label = sport.upper()
            today_label = datetime.now().strftime("%B %d, %Y")
            lines = [f"{emoji} <b>C&amp;P Picks — {label} Best Bets</b>", f"📅 {today_label}", ""]

            market_emoji = {"moneyline": "🎯", "spread": "📏", "total": "🔢"}
            for g in daily_games:
                parts = g["game"].split(" @ ")
                away, home = (parts[0], parts[1]) if len(parts) == 2 else ("", "")
                ctx = build_game_context(sport, home, away, rankings_by_team) if home and away else None

                lines.append(f"📌 <b>{g['game']}</b>")
                for pick in g["picks"]:
                    if ctx:
                        pick.ai_reasoning = generate_game_reasoning(ctx, pick)
                    pemoji = market_emoji.get(pick.market, "•")
                    odds_str = f" ({pick.odds})" if pick.odds else ""
                    lines.append(f"{pemoji} {pick.market.title()}: {pick.team_or_side}{odds_str} — {pick.edge_display}")
                    if pick.ai_reasoning:
                        lines.append(f"   💡 {pick.ai_reasoning}")
                lines.append("")

            # best-guaranteed prop spotlight
            try:
                from edge_finder import get_edge_finder
                from ai_prop_analyzer import generate_prop_analysis
                today_str = datetime.now().strftime("%Y-%m-%d")
                all_edges = get_edge_finder(date=today_str, sport=sport, top_n=20)
                best_props = [p for p in all_edges if p.get("edge_score", 0) >= 85]
                best_props.sort(key=lambda p: p.get("edge_score", 0), reverse=True)
                best_props = best_props[:2]
                if best_props:
                    lines.append("🔒 <b>BEST GUARANTEED PROP" + ("S" if len(best_props) > 1 else "") + "</b>")
                    for p in best_props:
                        direction = "Over" if p.get("projection_direction") == "over" else "Under"
                        lines.append(f"⭐ {p.get('player_name', 'Unknown')} — {p.get('stat', '').upper()} {direction} {p.get('line', '')}")
                        try:
                            reasoning = generate_prop_analysis(p, sport)
                            if reasoning:
                                lines.append(f"   💡 {reasoning}")
                        except Exception:
                            pass
                    lines.append("")
            except Exception as e:
                log(f"Edge Finder prop spotlight failed (non-fatal): {e}")

            lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
            sent = send_discord_alert("\n".join(lines), sport)

            if sent:
                log(f"Sent leaner {label} alert covering {len(daily_games)} game(s).")
            else:
                log(f"Leaner {label} alert FAILED to reach Discord (games/predictions still logged to DB).")
            return sent

        except Exception as e:
            log(f"Leaner alert error: {e}")
            return False

    # ── ORIGINAL per-bet flow (all other sports, unchanged) ──
    try:
        from telegram_alerts import format_game_card, get_game_times, get_recommended_prob

        game_times, game_times_raw = get_game_times(sport)

        from telegram_alerts import get_raw_time_for_bet, is_today_ct
        clean_bets = []
        for bet in bets:
            raw_time = get_raw_time_for_bet(bet, game_times_raw)
            if raw_time and not is_today_ct(raw_time):
                log(f"Skipping stale game: {bet.get('game')} — {raw_time}")
                continue

            recommended_prob = get_recommended_prob(bet)
            if recommended_prob < 55:
                log(f"Skipping low confidence: {bet.get('game')} — {recommended_prob}%")
                continue

            # PREDICTION ENGINE v2: this path already treats each bet
            # dict independently (one alert per bet, not grouped by
            # game), so multiple markets for the same game were never
            # collapsed into one here the way the WNBA/MLB leaner path
            # was. Still switched to the market-aware dedup check for
            # consistency — a game with a moneyline pick already sent
            # this morning can now still pick up a new spread/total
            # pick on retry instead of the whole game being skipped.
            if skip_if_already_alerted and already_alerted_today(sport, bet.get("game", ""), market=bet.get("market", "moneyline")):
                log(f"Already alerted today, skipping duplicate: {bet.get('game')} [{bet.get('market', 'moneyline')}]")
                continue

            clean_bets.append(bet)

        if not clean_bets:
            log(f"No {sport.upper()} bets met confidence threshold.")
            return False

        # ── THROTTLE: per-sport edge/confidence floor, one pick per
        # game, and a max-picks cap (see alert_throttle.THROTTLE_CONFIG)
        # — same filter the WNBA/MLB leaner path gets via
        # game_pick_selector, now applied here too so NFL/CFB/etc. can't
        # blow past the min_edge floor set for them.
        try:
            from alert_throttle import throttle_bets
            clean_bets, suppressed, throttle_log = throttle_bets(clean_bets, sport)
            log(throttle_log)
        except Exception as e:
            log(f"Throttle error — falling back to confidence filter: {e}")
            clean_bets = [b for b in clean_bets if get_recommended_prob(b) >= 55]

        if not clean_bets:
            log(f"No {sport.upper()} bets survived throttle.")
            return False

        sent_count = 0
        for bet in clean_bets:
            try:
                from database import log_prediction
                log_prediction(bet, sport, market=bet.get("market", "moneyline"))
            except Exception as e:
                log(f"Prediction log error: {e}")

            game      = bet.get("game", "")
            game_time = game_times.get(game, "Time TBD")

            if game_time == "Time TBD":
                parts = game.split(" @ ")
                if len(parts) == 2:
                    game_time = game_times.get(parts[0], game_times.get(parts[1], "Time TBD"))

            if send_discord_alert(format_game_card(bet, sport, game_time), sport):
                sent_count += 1
            time.sleep(1)

        log(f"Sent {sent_count}/{len(clean_bets)} {sport.upper()} alerts.")
        return sent_count > 0

    except Exception as e:
        log(f"Alert formatting error: {e}")
        return False


# ─────────────────────────────────────────────────────────────
# RESULTS RUNNER
# ─────────────────────────────────────────────────────────────

def run_results():
    log("Pulling ESPN results...")
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "auto_results.py", "yesterday"],
            capture_output=True, text=True, timeout=120,
        )
        log(result.stdout)
        if result.returncode != 0:
            log(f"auto_results.py error: {result.stderr}")
        else:
            log("Results updated.")
    except Exception as e:
        log(f"Results tracker error: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def run(sports: list, retry: bool = False):
    log("══════════════════════════════════════════════")
    label = "Noon Retry" if retry else "Daily Run"
    log(f"Culture & Pulse — {label} — {datetime.now().strftime('%A %B %d, %Y')}")
    log(f"Sports: {', '.join(s.upper() for s in sports)}")
    log("══════════════════════════════════════════════")

    check_predictor_imports()

    wake_api()

    try:
        from telegram_alerts import is_in_season
    except Exception as e:
        log(f"Could not import season gates: {e}")
        return

    all_sharp_hits = []  # accumulated across every sport this run, for the per-sport steam alerts below

    for sport in sports:
        if not is_in_season(sport):
            log(f"{sport.upper()}: out of season — skipping")
            continue

        if retry:
            try:
                # Capture line movement FIRST, before any potential
                # re-alert. Previously this ran after run_alerts(),
                # which meant a fresh noon-retry pick was generated
                # and sent before movement data existed for that
                # game — log_line_movement() was purely writing a
                # record for later analysis, never actually feeding
                # a live prediction. Flipping the order means
                # run_alerts() -> predict() can now read a real
                # movement row via get_line_movement_adj() (wired
                # into wnba_predictor.py so far) if this retry finds
                # a new pick worth sending.
                try:
                    from services.odds_parser import get_live_odds
                    from database import log_line_movement, update_closing_odds
                    games_for_movement = get_live_odds(sport)
                    update_closing_odds(sport, games_for_movement)
                    sharp_hits = log_line_movement(sport, games_for_movement)
                    if sharp_hits:
                        all_sharp_hits.extend(sharp_hits)
                    log(f"Line movement captured for {sport}")
                except Exception as e:
                    log(f"Line movement error for {sport}: {e}")

                data = fetch_edges_with_retry(sport)  # see run_alerts() for why — real MLB timing, not a guess
                if data is None:
                    continue
                bets = data.get("best_bets", [])
                if any(b.get("model_prob", 0) >= 55 for b in bets):
                    log(f"{sport.upper()}: picks found on retry — checking for duplicates")
                    run_alerts(sport, skip_if_already_alerted=True)
                else:
                    log(f"{sport.upper()}: still no edges on retry — skipping")

            except Exception as e:
                log(f"Retry check error for {sport}: {e}")
        else:
            run_alerts(sport)

        time.sleep(5)

    # ── STEAM ALERT — split per sport, added 2026-07-23 ──
    # Previously ONE consolidated message covering every sport's sharp
    # line moves, sent to a single channel. Discord is now organized
    # per sport, so this groups all_sharp_hits by hit['sport'] and
    # sends one message per sport that actually had a hit, each to its
    # own channel — same pattern as recap_engine.py's restructure.
    if retry and all_sharp_hits:
        hits_by_sport = {}
        for hit in all_sharp_hits:
            hits_by_sport.setdefault(hit["sport"], []).append(hit)

        for sport, hits in hits_by_sport.items():
            lines = ["⚡ <b>Line Movement Alert</b>", ""]
            for hit in hits:
                lines.append(f"🏟 {hit['game']} ({hit['sport'].upper()})")
                lines.append(f"   {hit['detail']}")
            lines.append("")
            lines.append("Culture & Pulse Analytics | Line movement, not a pick.")
            send_discord_alert("\n".join(lines), sport)

        log(f"Sent {len(hits_by_sport)} steam alert(s) covering {len(all_sharp_hits)} game(s) across "
            f"{len(hits_by_sport)} sport(s)")

    if not retry:
        log("")
        run_results()

    log("══════════════════════════════════════════════")
    log(f"{label} complete.")
    log("══════════════════════════════════════════════")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport",   type=str, default=None,
                        help="Run one specific sport only (e.g. --sport wnba)")
    parser.add_argument("--exclude", type=str, default=None,
                        help="Exclude one sport from the run (e.g. --exclude wnba)")
    parser.add_argument("--retry",   action="store_true",
                        help="Noon retry run for missed morning picks")
    args = parser.parse_args()

    if args.sport:
        sports = [args.sport.lower()]
    elif args.exclude:
        sports = [s for s in ALL_SPORTS if s != args.exclude.lower()]
    else:
        sports = ALL_SPORTS

    run(sports=sports, retry=args.retry)