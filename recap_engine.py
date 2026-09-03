"""
recap_engine.py — Culture & Pulse Analytics
=============================================
Unified daily/weekly Telegram recap across ALL sports.
Replaces wnba_recap.py. Reads via database.get_conn() — this comment
used to say "Turso only," written before the Supabase migration
existed; get_conn() itself decides the real backend based on which env
vars are present (SUPABASE_DB_URL first, Turso fallback), same as
every other file. results_tracker.py's separate results_log.json file
is retired, this is now the single source of truth for recaps.

RESTRUCTURED 2026-07-23: this used to build ONE combined message
covering every sport (with a "Total" line appended when more than one
sport had data) and send it to a single Recaps channel. Discord is now
organized per sport instead of by content type, so recaps for each
sport now get their OWN message, sent to that sport's own channel —
build_daily_message()/build_weekly_message() (singular, one sport)
replace the old build_daily_message()/build_weekly_message() that
built the combined multi-sport string. The "Total across all sports"
summary line is gone since there's no longer one shared message for it
to summarize — each sport's own recap already shows its own record.

Usage:
  python recap_engine.py --daily                 # all sports, yesterday (one message per sport with data)
  python recap_engine.py --daily --sport wnba     # one sport only
  python recap_engine.py --weekly
  python recap_engine.py --weekly --sport nfl
  python recap_engine.py --daily --dry-run        # print, don't send
"""

import os
import requests
import argparse
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Fallback webhook, kept from the old content-type migration — used
# only if get_webhook_for_sport(sport) can't find that sport's own
# DISCORD_WEBHOOK_* env var yet.
DISCORD_WEBHOOK_RECAPS = os.getenv("DISCORD_WEBHOOK_RECAPS", "")
CENTRAL_OFFSET   = -5

# Add a sport here and every recap (daily + weekly) picks it up automatically.
SPORTS = ["wnba", "nfl", "cfb", "ncaab", "mlb"]

SPORT_LABELS = {
    "wnba":  "🏀 WNBA",
    "nfl":   "🏈 NFL",
    "cfb":   "🏈 CFB",
    "ncaab": "🏀 NCAAB",
    "mlb":   "⚾ MLB",
}

CLEAN_DATA_START = {
    "wnba":  "2026-06-22",
    "nfl":   "2026-07-05",
    "cfb":   "2026-07-05",
    "ncaab": "2026-07-05",
    "mlb":   "2026-07-06",   # MLB's first live day
}


def get_conn():
    from database import get_conn as _get_conn
    return _get_conn()


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def _webhook_for(sport: str) -> str:
    """cfb/ncaab don't have a dedicated recap webhook naming mismatch
    to worry about — SPORTS keys here already match SPORT_WEBHOOK_ENV_VARS
    in discord_alerts.py (wnba/mlb/nfl/cfb/ncaab). Falls back to the old
    shared Recaps webhook if a sport's own var isn't set."""
    from discord_alerts import get_webhook_for_sport
    return get_webhook_for_sport(sport) or DISCORD_WEBHOOK_RECAPS


def send_message(text: str, sport: str):
    from discord_alerts import send_discord_message, html_to_discord_markdown
    ok = send_discord_message(html_to_discord_markdown(text), webhook_url=_webhook_for(sport))
    if ok:
        print(f"  Sent successfully ({sport}).")
    else:
        print(f"  Recap send failed for {sport} — see error above.")


def get_results(sport: str, start_date: str, end_date: str) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT r.date, r.sport, r.game, r.actual_winner, r.correct,
               r.home_team, r.away_team, r.home_score, r.away_score,
               p.bet, p.edge, p.odds, p.predicted_winner, p.market, p.line
        FROM results r
        JOIN predictions p ON r.prediction_id = p.id
        WHERE r.sport = ?
        AND r.date >= ? AND r.date <= ?
        AND r.correct IS NOT NULL
        ORDER BY r.date ASC
    """, (sport, start_date, end_date))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def format_result_display(r: dict) -> str:
    """What actually happened, for the recap's "Pick: ... -> result" line.

    FIXED 2026-09-03: this used to always show r['actual_winner'] (a
    team name) regardless of market — meaningless for a total pick like
    "Over 8.5", which produced results like "Over 8.5 -> Milwaukee
    Brewers" (a team name is not a result for a bet on combined score).
    Grading itself (auto_results.score_prediction) was already correct —
    it compares actual_total to the line, not who won — this was purely
    a display bug downstream of correct data. Spread bets keep showing
    the winner for now (out of scope of the total-display bug reported);
    that display has its own, smaller version of the same issue (winning
    outright isn't the same as covering) but isn't what was asked here."""
    if r.get("market") == "total" and r.get("home_score") is not None and r.get("away_score") is not None:
        actual_total = r["home_score"] + r["away_score"]
        return f"{r['home_team']} {r['home_score']} - {r['away_score']} {r['away_team']} (Total: {actual_total})"
    return r["actual_winner"]


def parse_odds(odds_str):
    """American odds -> decimal payout multiplier. None if unparseable."""
    try:
        odds = int(str(odds_str).replace(" ", ""))
        return odds / 100.0 if odds > 0 else 100.0 / abs(odds)
    except Exception:
        return None


def calc_roi(rows: list) -> dict:
    """Ported from results_tracker.py — flat 1-unit bet, -110 default if no odds."""
    DEFAULT_RETURN = 100 / 110
    net_units = 0.0
    for r in rows:
        mult = parse_odds(r.get("odds"))
        if mult is None:
            mult = DEFAULT_RETURN
        net_units += mult if r["correct"] == 1 else -1.0
    total = len(rows)
    roi_pct = (net_units / total * 100) if total else 0
    return {"net_units": round(net_units, 2), "roi_pct": round(roi_pct, 2)}


def format_record(wins, total):
    losses = total - wins
    pct = round(wins / total * 100, 1) if total else 0
    return f"{wins}-{losses} ({pct}%)"


def sport_daily_block(sport: str, date_str: str):
    """Returns (formatted block, wins, total) for one sport on one date."""
    rows = get_results(sport, date_str, date_str)
    if not rows:
        return "", 0, 0

    wins = sum(1 for r in rows if r["correct"] == 1)

    label = SPORT_LABELS.get(sport, sport.upper())
    lines = [f"{label} — {format_record(wins, len(rows))}"]
    for r in rows:
        icon = "✅" if r["correct"] == 1 else "❌"
        edge_str = f" | Edge +{r['edge']}%" if r["edge"] and r["edge"] >= 10 else ""
        lines.append(f"  {icon} {r['game']}")
        lines.append(f"     Pick: {r['bet']}{edge_str} → <b>{format_result_display(r)}</b>")

    return "\n".join(lines), wins, len(rows)


def build_daily_message(sport: str, date_str: str) -> str:
    """Returns the full daily recap message for ONE sport, or "" if
    that sport had no scored results on this date. Singular now —
    replaces the old multi-sport combined builder (see module
    docstring, 2026-07-23 restructure)."""
    block, wins, total = sport_daily_block(sport, date_str)
    if not block:
        return ""

    header = f"📊 <b>C&amp;P Picks — Daily Recap</b>\n📅 {date_str}\n"
    lines = [header, block, "\n<i>Culture &amp; Pulse Analytics | For entertainment only.</i>"]
    return "\n".join(lines)


def build_weekly_message(sport: str, week_start: str, week_end: str) -> str:
    """Returns the full weekly recap message for ONE sport, or "" if
    that sport had no data (this week or season-to-date). Singular
    now — replaces the old multi-sport combined builder."""
    rows = get_results(sport, week_start, week_end)
    clean_start = CLEAN_DATA_START.get(sport, week_start)
    season_rows = get_results(sport, clean_start, week_end)

    if not rows and not season_rows:
        return ""

    label = SPORT_LABELS.get(sport, sport.upper())
    lines = [f"📊 <b>C&amp;P Picks — Weekly Recap</b>\n📅 Week of {week_start}\n", f"<b>{label}</b>"]

    if rows:
        wins = sum(1 for r in rows if r["correct"] == 1)
        roi = calc_roi(rows)
        sign = "+" if roi["net_units"] >= 0 else ""
        lines.append(f"  This week: {format_record(wins, len(rows))}  |  {sign}{roi['net_units']}u")
    else:
        lines.append("  This week: no scored results")

    if season_rows:
        s_wins = sum(1 for r in season_rows if r["correct"] == 1)
        roi = calc_roi(season_rows)
        sign = "+" if roi["net_units"] >= 0 else ""
        lines.append(f"  Season (since {clean_start}): {format_record(s_wins, len(season_rows))}  |  {sign}{roi['net_units']}u")

        correct_picks = [r for r in season_rows if r["correct"] == 1 and r["edge"]]
        best = max(correct_picks, key=lambda x: x["edge"], default=None)
        if best:
            lines.append(f"  🔥 Best: {best['bet']} (+{best['edge']}%) — {best['game']}")

    lines.append("")
    lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
    return "\n".join(lines)


def run(mode: str, sport_filter: str = None, dry_run: bool = False):
    today = get_today_ct()
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    sports = [sport_filter] if sport_filter else SPORTS

    any_sent = False

    for sport in sports:
        if mode == "daily":
            msg = build_daily_message(sport, yesterday)
            desc = f"Daily recap for {yesterday} ({sport})"
        elif mode == "weekly":
            days_since_monday = today.weekday()
            week_start = (today - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")
            week_end = yesterday
            msg = build_weekly_message(sport, week_start, week_end)
            desc = f"Weekly recap for {week_start} to {week_end} ({sport})"
        else:
            return

        if not msg:
            continue  # no data for this sport — skip silently, same as before

        any_sent = True
        print(desc)
        if dry_run:
            print("--- DRY RUN ---")
            print(msg)
            print()
        else:
            send_message(msg, sport)

    if not any_sent:
        print(f"No scored results for any sport yet ({mode}).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", action="store_true")
    parser.add_argument("--weekly", action="store_true")
    parser.add_argument("--sport", default=None, help="Limit to one sport (wnba, nfl, cfb, ncaab)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.daily:
        run("daily", sport_filter=args.sport, dry_run=args.dry_run)
    elif args.weekly:
        run("weekly", sport_filter=args.sport, dry_run=args.dry_run)
    else:
        print("Usage: python recap_engine.py --daily or --weekly [--sport X] [--dry-run]")
