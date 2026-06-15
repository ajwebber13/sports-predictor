"""
model_report.py — Culture & Pulse Analytics
Pulls win rate, ROI, and edge accuracy from cp_analytics.db
Run anytime to see how the model is performing.

Usage:
  python model_report.py           # full report
  python model_report.py wnba      # single sport
  python model_report.py telegram  # send report to Telegram
"""

import os
import requests
from datetime import datetime
from database import get_conn, init_db

# Ensure DB exists on fresh environments (GitHub Actions)
try:
    init_db()
except Exception:
    pass

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHANNEL = "@cultureandpulsepicks"


def get_overall_stats() -> dict:
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT
            COUNT(*)                        as total_picks,
            SUM(correct)                    as total_wins,
            ROUND(AVG(correct) * 100, 1)    as win_rate,
            ROUND(AVG(edge_at_pick), 1)     as avg_edge,
            MIN(date)                       as first_pick,
            MAX(date)                       as last_pick
        FROM results
        WHERE correct IS NOT NULL
    """)
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}


def get_sport_breakdown() -> list:
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT
            sport,
            COUNT(*)                        as picks,
            SUM(correct)                    as wins,
            ROUND(AVG(correct) * 100, 1)    as win_rate,
            ROUND(AVG(edge_at_pick), 1)     as avg_edge,
            ROUND(AVG(odds_at_pick), 0)     as avg_odds
        FROM results
        WHERE correct IS NOT NULL
        GROUP BY sport
        ORDER BY win_rate DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_edge_breakdown() -> list:
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT
            CASE
                WHEN edge_at_pick >= 20 THEN '20%+ edge'
                WHEN edge_at_pick >= 15 THEN '15-20% edge'
                WHEN edge_at_pick >= 10 THEN '10-15% edge'
                WHEN edge_at_pick >= 5  THEN '5-10% edge'
                ELSE 'Under 5% edge'
            END as edge_tier,
            COUNT(*)                        as picks,
            SUM(correct)                    as wins,
            ROUND(AVG(correct) * 100, 1)    as win_rate
        FROM results
        WHERE correct IS NOT NULL
        GROUP BY edge_tier
        ORDER BY win_rate DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_form(days: int = 7) -> dict:
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT
            COUNT(*)                        as picks,
            SUM(correct)                    as wins,
            ROUND(AVG(correct) * 100, 1)    as win_rate
        FROM results
        WHERE correct IS NOT NULL
        AND date >= date('now', ?)
    """, (f"-{days} days",))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else {}


def calculate_roi(avg_odds: float, win_rate: float) -> float:
    if not avg_odds or not win_rate:
        return 0.0
    win_rate_dec   = win_rate / 100
    loss_rate      = 1 - win_rate_dec
    if avg_odds > 0:
        profit_per_win = avg_odds / 100
    else:
        profit_per_win = 100 / abs(avg_odds)
    roi = (win_rate_dec * profit_per_win) - (loss_rate * 1.0)
    return round(roi * 100, 1)


def print_report(sport: str = None):
    overall = get_overall_stats()
    sports  = get_sport_breakdown()
    edges   = get_edge_breakdown()
    recent  = get_recent_form(7)

    if not overall.get("total_picks"):
        print("\nNo results logged yet. Keep picking — data builds over time.")
        return

    print(f"\n{'='*55}")
    print(f"  📊 CULTURE & PULSE — MODEL PERFORMANCE REPORT")
    print(f"  {datetime.now().strftime('%B %d, %Y')}")
    print(f"{'='*55}")

    total = overall.get("total_picks", 0)
    wins  = overall.get("total_wins", 0)
    rate  = overall.get("win_rate", 0)
    edge  = overall.get("avg_edge", 0)
    first = overall.get("first_pick", "")
    last  = overall.get("last_pick", "")

    print(f"\n  OVERALL")
    print(f"  {'─'*45}")
    print(f"  Record:     {wins}-{total-wins} ({rate}% win rate)")
    print(f"  Avg Edge:   +{edge}%")
    print(f"  Period:     {first} → {last}")

    if recent.get("picks"):
        r_picks = recent.get("picks", 0)
        r_wins  = recent.get("wins", 0)
        r_rate  = recent.get("win_rate", 0)
        print(f"  Last 7 days: {r_wins}-{r_picks-r_wins} ({r_rate}%)")

    if sports:
        print(f"\n  BY SPORT")
        print(f"  {'─'*45}")
        print(f"  {'Sport':<10} {'Record':<12} {'Win%':<10} {'Avg Edge':<12} {'ROI'}")
        print(f"  {'─'*45}")
        for s in sports:
            if sport and s["sport"] != sport:
                continue
            w       = s["wins"] or 0
            p       = s["picks"]
            l       = p - w
            rate_s  = s["win_rate"] or 0
            edge_s  = s["avg_edge"] or 0
            odds_s  = s["avg_odds"] or -110
            roi     = calculate_roi(odds_s, rate_s)
            roi_str = f"+{roi}%" if roi >= 0 else f"{roi}%"
            print(f"  {s['sport'].upper():<10} {w}-{l:<10} {rate_s}%{'':<6} +{edge_s}%{'':<8} {roi_str}")

    if edges:
        print(f"\n  BY EDGE TIER")
        print(f"  {'─'*45}")
        print(f"  {'Tier':<18} {'Picks':<8} {'Wins':<8} {'Win Rate'}")
        print(f"  {'─'*45}")
        for e in edges:
            w = e["wins"] or 0
            p = e["picks"]
            print(f"  {e['edge_tier']:<18} {p:<8} {w:<8} {e['win_rate']}%")

    print(f"\n{'='*55}\n")


def send_telegram_report():
    overall = get_overall_stats()
    sports  = get_sport_breakdown()
    recent  = get_recent_form(7)

    if not overall.get("total_picks"):
        print("No results yet — skipping Telegram report.")
        return

    total = overall.get("total_picks", 0)
    wins  = int(overall.get("total_wins", 0))
    rate  = overall.get("win_rate", 0)
    edge  = overall.get("avg_edge", 0)

    lines = [
        "📊 <b>Culture &amp; Pulse — Model Report</b>",
        f"📅 {datetime.now().strftime('%B %d, %Y')}\n",
        f"<b>Overall Record:</b> {wins}-{total-wins} ({rate}% win rate)",
        f"<b>Avg Edge:</b> +{edge}%",
    ]

    if recent.get("picks"):
        r_wins  = int(recent.get("wins", 0))
        r_picks = recent.get("picks", 0)
        r_rate  = recent.get("win_rate", 0)
        lines.append(f"<b>Last 7 Days:</b> {r_wins}-{r_picks-r_wins} ({r_rate}%)")

    if sports:
        lines.append("\n<b>BY SPORT</b>")
        for s in sports:
            w       = int(s["wins"] or 0)
            p       = s["picks"]
            roi     = calculate_roi(s["avg_odds"] or -110, s["win_rate"] or 0)
            roi_str = f"+{roi}%" if roi >= 0 else f"{roi}%"
            lines.append(
                f"{s['sport'].upper()}: {w}-{p-w} "
                f"({s['win_rate']}%) | ROI {roi_str}"
            )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("<i>Culture &amp; Pulse Analytics</i>")

    msg = "\n".join(lines)

    if not TELEGRAM_TOKEN:
        print("No Telegram token — skipping send.")
        print(msg)
        return

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHANNEL, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.status_code == 200:
            print("Report sent to Telegram.")
        else:
            print(f"Telegram error: {r.status_code}")
    except Exception as e:
        print(f"Telegram exception: {e}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "telegram":
            send_telegram_report()
        else:
            print_report(sport=arg)
    else:
        print_report()