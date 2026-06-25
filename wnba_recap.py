"""
wnba_recap.py — Culture & Pulse Analytics
==========================================
Sends daily and weekly WNBA performance recaps to Telegram.

Usage:
  python wnba_recap.py --daily     # yesterday's results
  python wnba_recap.py --weekly    # this week's summary (run Sundays)
  python wnba_recap.py --dry-run   # print without sending
"""

import os
import requests
import argparse
import sqlite3
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"
CENTRAL_OFFSET   = -5
CLEAN_DATA_START = "2026-06-22"


def get_conn():
    from database import get_conn as _get_conn
    return _get_conn()


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def send_message(text: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":                  TELEGRAM_CHANNEL,
        "text":                     text,
        "parse_mode":               "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=10)
    if r.status_code == 200:
        print("Sent successfully.")
    else:
        print(f"Telegram error: {r.status_code} {r.text}")


def get_results(start_date: str, end_date: str) -> list:
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT r.date, r.game, r.actual_winner, r.correct,
               p.bet, p.edge, p.odds, p.predicted_winner
        FROM results r
        JOIN predictions p ON r.prediction_id = p.id
        WHERE r.sport = 'wnba'
        AND r.date >= ? AND r.date <= ?
        AND r.correct IS NOT NULL
        ORDER BY r.date ASC
    """, (start_date, end_date))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return rows


def format_record(wins, total):
    losses  = total - wins
    pct     = round(wins / total * 100, 1) if total > 0 else 0
    return f"{wins}-{losses} ({pct}%)"


def build_daily_message(date_str: str) -> str:
    rows = get_results(date_str, date_str)

    if not rows:
        return (
            f"🏀 <b>C&amp;P Picks — Daily Recap</b>\n"
            f"📅 {date_str}\n\n"
            f"No scored results for this date yet."
        )

    all_wins   = sum(1 for r in rows if r["correct"] == 1)
    edge_rows  = [r for r in rows if r["edge"] and r["edge"] >= 10]
    edge_wins  = sum(1 for r in edge_rows if r["correct"] == 1)

    lines = [
        "🏀 <b>C&amp;P Picks — Daily Recap</b>",
        f"📅 {date_str}\n",
        f"📊 <b>Yesterday's Results</b>",
    ]

    for r in rows:
        icon = "✅" if r["correct"] == 1 else "❌"
        edge_str = f" | Edge +{r['edge']}%" if r["edge"] and r["edge"] >= 10 else ""
        lines.append(f"{icon} {r['game']}")
        lines.append(f"   Pick: {r['bet']}{edge_str} → <b>{r['actual_winner']}</b>")

    lines.append("")
    lines.append(f"📋 <b>Overall:</b> {format_record(all_wins, len(rows))}")
    if edge_rows:
        lines.append(f"🎯 <b>Edge picks:</b> {format_record(edge_wins, len(edge_rows))}")
    lines.append("")
    lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")

    return "\n".join(lines)


def build_weekly_message(week_start: str, week_end: str) -> str:
    rows         = get_results(week_start, week_end)
    season_rows  = get_results(CLEAN_DATA_START, week_end)

    if not rows:
        return (
            f"🏀 <b>C&amp;P Picks — Weekly Recap</b>\n"
            f"📅 Week of {week_start}\n\n"
            f"No scored results this week yet."
        )

    all_wins      = sum(1 for r in rows if r["correct"] == 1)
    edge_rows     = [r for r in rows if r["edge"] and r["edge"] >= 10]
    edge_wins     = sum(1 for r in edge_rows if r["correct"] == 1)

    season_wins   = sum(1 for r in season_rows if r["correct"] == 1)
    season_edge   = [r for r in season_rows if r["edge"] and r["edge"] >= 10]
    season_e_wins = sum(1 for r in season_edge if r["correct"] == 1)

    # Best pick of the week
    correct_picks = [r for r in rows if r["correct"] == 1 and r["edge"]]
    best_pick     = max(correct_picks, key=lambda x: x["edge"], default=None)

    # Worst miss of the week
    wrong_picks = [r for r in rows if r["correct"] == 0 and r["edge"]]
    worst_miss  = max(wrong_picks, key=lambda x: x["edge"], default=None)

    lines = [
        "🏀 <b>C&amp;P Picks — Weekly Recap</b>",
        f"📅 Week of {week_start}\n",
        f"<b>THIS WEEK</b>",
        f"📊 Overall: {format_record(all_wins, len(rows))}",
    ]
    if edge_rows:
        lines.append(f"🎯 Edge picks: {format_record(edge_wins, len(edge_rows))}")

    lines.append("")
    lines.append(f"<b>SEASON (since {CLEAN_DATA_START})</b>")
    lines.append(f"📊 Overall: {format_record(season_wins, len(season_rows))}")
    if season_edge:
        lines.append(f"🎯 Edge picks: {format_record(season_e_wins, len(season_edge))}")

    if best_pick:
        lines.append("")
        lines.append(f"🔥 <b>Best Pick:</b> {best_pick['bet']} (+{best_pick['edge']}%) ✅")
        lines.append(f"   {best_pick['game']}")

    if worst_miss:
        lines.append("")
        lines.append(f"💔 <b>Worst Miss:</b> {worst_miss['bet']} (+{worst_miss['edge']}%) ❌")
        lines.append(f"   {worst_miss['game']}")

    lines.append("")
    lines.append("<i>Culture &amp; Pulse Analytics | For entertainment only.</i>")

    return "\n".join(lines)


def run(mode: str, dry_run: bool = False):
    today     = get_today_ct()
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    if mode == "daily":
        msg = build_daily_message(yesterday)
        print(f"Daily recap for {yesterday}")

    elif mode == "weekly":
        # Week runs Mon-Sun, recap fires Sunday
        days_since_monday = today.weekday()
        week_start = (today - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")
        week_end   = yesterday
        msg = build_weekly_message(week_start, week_end)
        print(f"Weekly recap for {week_start} to {week_end}")

    if dry_run:
        print("\n--- DRY RUN ---")
        print(msg)
    else:
        send_message(msg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily",   action="store_true")
    parser.add_argument("--weekly",  action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.daily:
        run("daily", dry_run=args.dry_run)
    elif args.weekly:
        run("weekly", dry_run=args.dry_run)
    else:
        print("Usage: python wnba_recap.py --daily or --weekly [--dry-run]")