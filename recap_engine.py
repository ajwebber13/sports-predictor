"""
recap_engine.py — Culture & Pulse Analytics
=============================================
Unified daily/weekly Telegram recap across ALL sports.
Replaces wnba_recap.py. Reads only from Turso via database.get_conn() —
results_tracker.py's separate results_log.json file is retired, this
is now the single source of truth for recaps.

Usage:
  python recap_engine.py --daily                 # all sports, yesterday
  python recap_engine.py --daily --sport wnba     # one sport only
  python recap_engine.py --weekly
  python recap_engine.py --weekly --sport nfl
  python recap_engine.py --daily --dry-run        # print, don't send
"""

import os
import requests
import argparse
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"
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


def send_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("Sent successfully.")
    else:
        print(f"Telegram error: {r.status_code} {r.text}")


def get_results(sport: str, start_date: str, end_date: str) -> list:
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT r.date, r.sport, r.game, r.actual_winner, r.correct,
               p.bet, p.edge, p.odds, p.predicted_winner
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
    edge_rows = [r for r in rows if r["edge"] and r["edge"] >= 10]

    label = SPORT_LABELS.get(sport, sport.upper())
    lines = [f"{label} — {format_record(wins, len(rows))}"]
    for r in rows:
        icon = "✅" if r["correct"] == 1 else "❌"
        edge_str = f" | Edge +{r['edge']}%" if r["edge"] and r["edge"] >= 10 else ""
        lines.append(f"  {icon} {r['game']}")
        lines.append(f"     Pick: {r['bet']}{edge_str} → <b>{r['actual_winner']}</b>")

    return "\n".join(lines), wins, len(rows)


def build_daily_message(date_str: str, sport_filter: str = None) -> str:
    sports = [sport_filter] if sport_filter else SPORTS

    blocks = []
    total_wins = 0
    total_games = 0

    for sport in sports:
        block, wins, total = sport_daily_block(sport, date_str)
        if block:
            blocks.append(block)
            total_wins += wins
            total_games += total

    header = f"📊 <b>C&amp;P Picks — Daily Recap</b>\n📅 {date_str}\n"

    if not blocks:
        return header + "\nNo scored results for this date yet."

    body = "\n\n".join(blocks)
    lines = [header, body]

    if len(sports) > 1:
        lines.append(f"\n📋 <b>Total:</b> {format_record(total_wins, total_games)}")

    lines.append("\n<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
    return "\n".join(lines)


def build_weekly_message(week_start: str, week_end: str, sport_filter: str = None) -> str:
    sports = [sport_filter] if sport_filter else SPORTS
    lines = [f"📊 <b>C&amp;P Picks — Weekly Recap</b>\n📅 Week of {week_start}\n"]

    any_data = False
    for sport in sports:
        rows = get_results(sport, week_start, week_end)
        clean_start = CLEAN_DATA_START.get(sport, week_start)
        season_rows = get_results(sport, clean_start, week_end)

        if not rows and not season_rows:
            continue
        any_data = True

        label = SPORT_LABELS.get(sport, sport.upper())
        lines.append(f"<b>{label}</b>")

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

    if not any_data:
        lines.append("No scored results this week yet.")
        return "\n".join(lines)

    lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")
    return "\n".join(lines)


def run(mode: str, sport_filter: str = None, dry_run: bool = False):
    today = get_today_ct()
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    if mode == "daily":
        msg = build_daily_message(yesterday, sport_filter)
        print(f"Daily recap for {yesterday}" + (f" ({sport_filter})" if sport_filter else " (all sports)"))

    elif mode == "weekly":
        days_since_monday = today.weekday()
        week_start = (today - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")
        week_end = yesterday
        msg = build_weekly_message(week_start, week_end, sport_filter)
        print(f"Weekly recap for {week_start} to {week_end}")

    else:
        return

    if dry_run:
        print("\n--- DRY RUN ---")
        print(msg)
    else:
        send_message(msg)


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
