"""
wnba_props_alert.py — Culture & Pulse Analytics
=================================================
Sends a standalone Telegram alert with today's player props,
grouped BY GAME (so the audience knows who's playing who), with
each player labeled by team. Pulled from the player_props table
(populated daily by fetch_prizepicks_props.py).

IMPORTANT — how tiers work:
  confidence_tier is set in prop_hit_rates.py based on hit_rate_overall
  (player's historical hit rate on THIS line) plus two adjustments:
    - situational flags (struggles vs this opponent / worse home-away /
      worse on B2B) can hold a tier down even at a high overall rate
    - off-role downgrade: a PTS prop on a player whose primary category
      isn't "scorer" (see wnba_player_categories.py) drops one tier,
      since points is the highest-variance stat for non-scorers
  Base tier thresholds (unchanged — same ones the dashboard uses):
    >= 65%        -> green
    50% - 64.9%   -> yellow
    < 50% / None  -> red
  "Hit" = actual_value > line, i.e. an OVER.

  Telegram-specific floor:
  This alert only surfaces green-tier props at hit_rate_overall >= 80%
  (STRONG_THRESHOLD), stricter than the 65% green cutoff itself — cuts
  noise from marginal green props that clear 65% but aren't strong
  enough to headline an alert. The dashboard still shows all green
  props at 65%+; this floor only affects what gets sent to Telegram.

  Sample size floor:
  hit_rate_overall alone is meaningless on 1-2 games (it can only be
  0% or 100%). MIN_GAMES filters those out before they ever reach the
  tier logic below, regardless of what the raw rate says.

  Game grouping:
  player_props stores game_home_team / game_away_team (the two teams
  in today's specific matchup) as of the 2026-07-04 fix. Each player's
  own team is looked up separately from their most recent wnba_game_log
  entry, since PropLine's feed doesn't include team assignment per prop.

Fade signal (unders):
  All prop lines are half-points (X.5), so there's no push case — a game
  either clears the line or doesn't. That means the under rate is exact,
  not approximate: under_rate = 100 - hit_rate_overall. No separate model
  needed. Props with hit_rate_overall <= 20 (i.e. under_rate >= 80) get
  surfaced as fades, same 80% floor as the over side, since a low
  over-rate is a real signal to play the under, not just noise to exclude.

Message formatting (updated 2026-07-05):
  Teams are shown as 3-letter abbreviations (TEAM_ABBR) instead of full
  names to cut visual clutter in long alerts. A divider line separates
  each game block so the audience can tell at a glance where one
  matchup ends and the next begins.

Run order each day (fully automated via GitHub Actions):
  1. fetch_prizepicks_props.py runs on its own schedule (10 AM CT) —
     pulls today's lines from PropLine, grades them, writes to player_props
  2. wnba_props_alert.py runs shortly after (10:15 AM CT, waits on
     fetch_props via needs: in the workflow) — reads whatever
     fetch_prizepicks_props.py just wrote and sends this alert

Usage:
    py wnba_props_alert.py            # send today's alert
    py wnba_props_alert.py --dry-run  # print instead of sending
"""

import os
import sys
import argparse
import time
import requests
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from database import get_conn
from prop_hit_rates import setup_props_table
from active_sports import props_active

# ── Config ────────────────────────────────────────────────────────────────────
CENTRAL_OFFSET = -5

# Fallback webhook, kept from the old content-type migration — used
# only if get_webhook_for_sport("wnba") can't find DISCORD_WEBHOOK_WNBA.
DISCORD_WEBHOOK_PROPS = os.getenv("DISCORD_WEBHOOK_PROPS", "")

# ── Selector (rewritten 2026-09-04) ──────────────────────────────────────────
# The old rule picked by historical hit rate (>=80 over / <=20 under).
# Backtest on 3,241 graded WNBA props: that rule LOST money, and making
# the projection engine "agree" with history made it worse (-22% ROI).
# Past hit rate is not a signal on lines the book already prices.
#
# What actually held up: projection engine tier = green, OVERS only,
# on combo/points stats (PA +13.5%, PRA +5.7%, PTS ~flat on 100-170
# picks each). Rebounds/assists alone lost, and every UNDER category
# lost across the board. So:
PROJECTION_TIER = "green"
ALLOWED_STATS = ("pa", "pra", "pts")   # add "pr" once it backtests positive
MIN_EDGE_PCT = 20.0                    # projection_edge_pct floor; raise to 20-35 for a shorter, sharper list
MAX_PICKS = 8                          # never post more than this — a long list is noise, not value
STRONG_THRESHOLD = 80  # kept for prop_tracker.py --picks-only compatibility; NOT used to pick anymore
FADE_THRESHOLD = 20    # same — fades are no longer posted (they lose)

# Minimum games behind a hit rate before it's trusted enough to alert on.
# 1-2 games can only produce 0% or 100%, which looks like a strong signal
# but is actually a coin flip.
MIN_GAMES = 5
MIN_GAMES_COLUMN = "games_overall"

STAT_LABELS = {
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "stl": "STL",
    "blk": "BLK",
    "3s":  "3PM",
    "pra": "PRA",
    "pr":  "PR",
    "pa":  "PA",
    "ra":  "RA",
}

WATCH_STATUSES = {"Day-To-Day", "Questionable", "Doubtful"}
INJURY_FLAG = {
    "Day-To-Day":  "DTD",
    "Questionable": "Q",
    "Doubtful":    "D",
}

TEAM_ABBR = {
    "Atlanta Dream":          "ATL",
    "Chicago Sky":            "CHI",
    "Connecticut Sun":        "CON",
    "Dallas Wings":           "DAL",
    "Golden State Valkyries": "GSV",
    "Indiana Fever":          "IND",
    "Las Vegas Aces":         "LVA",
    "Los Angeles Sparks":     "LAL",
    "Minnesota Lynx":         "MIN",
    "New York Liberty":       "NYL",
    "Phoenix Mercury":        "PHX",
    "Portland Fire":          "POR",
    "Seattle Storm":          "SEA",
    "Toronto Tempo":          "TOR",
    "Washington Mystics":     "WAS",
}

DIVIDER = "\u2501" * 20  # ━━━━━━━━━━━━━━━━━━━━


def abbr(team: str) -> str:
    return TEAM_ABBR.get(team, team.split()[-1] if team else "")


def get_today_ct():
    return (datetime.now(timezone.utc) + timedelta(hours=CENTRAL_OFFSET)).date()


def get_player_team(player_name: str) -> str:
    """Look up a player's most recent team from wnba_game_log.
    Returns '' if not found (e.g. brand new player with no logged games)."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT team_name FROM wnba_game_log
        WHERE player_name = ?
        ORDER BY date DESC
        LIMIT 1
    """, (player_name,))
    row = c.fetchone()
    conn.close()
    return row["team_name"] if row else ""


def fetch_today_props(date_str: str):
    """Today's OVER plays chosen by the projection engine: tier green,
    direction over, stat in ALLOWED_STATS, ranked by projection edge.
    Hit-rate history is carried along for display only."""
    conn = get_conn()
    c = conn.cursor()
    placeholders = ",".join("?" for _ in ALLOWED_STATS)
    c.execute(f"""
        SELECT player_name, stat, line, hit_rate_overall, games_overall, confidence_tier,
               injury_status, game_home_team, game_away_team, over_odds,
               projected_stat, projection_edge_pct, projection_direction, projection_tier
        FROM player_props
        WHERE date = ? AND sport = 'wnba'
          AND projection_tier = ?
          AND projection_direction = 'over'
          AND stat IN ({placeholders})
          AND projection_edge_pct IS NOT NULL
          AND projection_edge_pct >= ?
        ORDER BY projection_edge_pct DESC
    """, (date_str, PROJECTION_TIER, *ALLOWED_STATS, MIN_EDGE_PCT))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    # One prop per player: keep the biggest-edge stat so we never post
    # PTS, PA and PRA on the same player (they're the same bet three ways).
    best_by_player = {}
    for r in rows:
        if r["player_name"] not in best_by_player:
            best_by_player[r["player_name"]] = r
    return list(best_by_player.values())[:MAX_PICKS]


def fetch_fade_props(date_str: str):
    """Fades (unders) are no longer posted. Every under category lost in
    the 2026-09-04 backtest (green-tier unders -8.6% ROI, hit-rate
    unders far worse). Kept as a stub so nothing that imports it breaks."""
    return []


def format_line(prop: dict, team: str, emoji: str, seen_players: set) -> str:
    stat_label = STAT_LABELS.get(prop["stat"], prop["stat"].upper())
    pct        = prop.get("hit_rate_overall")
    pct_str    = (f"{pct:.1f}".rstrip("0").rstrip(".") if pct % 1 else f"{int(pct)}") if pct is not None else ""
    name       = (prop["player_name"]
                  .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    team_str   = f" ({abbr(team)})" if team else ""

    flag = ""
    status = prop.get("injury_status")
    if status in WATCH_STATUSES and prop["player_name"] not in seen_players:
        flag = f" \u26a0\ufe0f {INJURY_FLAG.get(status, status)}"

    seen_players.add(prop["player_name"])
    # "o" prefix matches format_fade_line()'s existing "u" prefix — every
    # line now shows its direction instead of only unders being labeled.
    proj = prop.get("projected_stat")
    edge = prop.get("projection_edge_pct")
    proj_str = f"proj {float(proj):.1f}" if proj is not None else ""
    edge_str = f" (+{float(edge):.0f}%)" if edge is not None else ""
    hist_str = f" \u00b7 hist {pct_str}% ({prop.get('games_overall') or 0}G)" if pct is not None else ""
    return (f"{emoji} {name}{team_str} \u2014 o{stat_label} {prop['line']:g} \u2014 "
            f"{proj_str}{edge_str}{hist_str}{flag}")


def format_fade_line(prop: dict, team: str, seen_players: set) -> str:
    stat_label = STAT_LABELS.get(prop["stat"], prop["stat"].upper())
    over_pct   = prop["hit_rate_overall"]
    under_pct  = round(100 - over_pct, 1)
    pct_str    = f"{under_pct:.1f}".rstrip("0").rstrip(".") if under_pct % 1 else f"{int(under_pct)}"
    name       = (prop["player_name"]
                  .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    team_str   = f" ({abbr(team)})" if team else ""

    flag = ""
    status = prop.get("injury_status")
    if status in WATCH_STATUSES and prop["player_name"] not in seen_players:
        flag = f" \u26a0\ufe0f {INJURY_FLAG.get(status, status)}"

    seen_players.add(prop["player_name"])
    return f"\U0001f53b {name}{team_str} \u2014 u{stat_label} {prop['line']:g} \u2014 {pct_str}%{flag}"


def build_message(date_str: str, props: list, fades: list = None) -> str:
    """Groups everything by game (away @ home) so the audience always
    knows which matchup a player's prop belongs to. A divider line
    separates each game block for readability."""
    fades = fades or []
    if not props and not fades:
        return ""

    pretty_date = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    lines = [
        "\U0001f3af <b>C&amp;P Player Props \u2014 WNBA</b>",
        f"\U0001f4c5 {pretty_date}",
        DIVIDER,
    ]

    seen = set()

    games = {}
    for p in props:
        away = p.get("game_away_team") or ""
        home = p.get("game_home_team") or ""
        key  = (away, home) if (away or home) else ("Unknown", "Matchup")
        games.setdefault(key, {"props": [], "fades": []})
        games[key]["props"].append(p)

    for f in fades:
        away = f.get("game_away_team") or ""
        home = f.get("game_home_team") or ""
        key  = (away, home) if (away or home) else ("Unknown", "Matchup")
        games.setdefault(key, {"props": [], "fades": []})
        games[key]["fades"].append(f)

    game_keys = list(games.keys())
    for i, (away, home) in enumerate(game_keys):
        bucket = games[(away, home)]
        lines.append(f"\U0001f3c0 <b>{abbr(away)} @ {abbr(home)}</b>")
        lines.append("")

        for p in sorted(bucket["props"], key=lambda x: float(x.get("projection_edge_pct") or 0), reverse=True):
            emoji = "\U0001f7e2"  # every pick here is projection-tier green by construction
            team  = get_player_team(p["player_name"])
            lines.append(format_line(p, team, emoji, seen))

        for f in bucket["fades"]:
            team = get_player_team(f["player_name"])
            lines.append(format_fade_line(f, team, seen))

        lines.append("")
        if i < len(game_keys) - 1:
            lines.append(DIVIDER)
            lines.append("")

    lines.append(DIVIDER)
    lines.append("<i>Culture &amp; Pulse Analytics</i>")
    lines.append("<i>For entertainment only. Bet responsibly.</i>")
    return "\n".join(lines).strip()


def send_message(text: str):
    from discord_alerts import send_discord_message, html_to_discord_markdown, get_webhook_for_sport
    # Routed to the WNBA channel, added 2026-07-23 — falls back to the
    # old props-only webhook if DISCORD_WEBHOOK_WNBA isn't set yet.
    webhook = get_webhook_for_sport("wnba") or DISCORD_WEBHOOK_PROPS
    send_discord_message(html_to_discord_markdown(text), webhook_url=webhook)


def run(dry_run: bool = False, date_override: str = None):
    if not props_active("wnba"):
        print("WNBA props are shelved in active_sports.py (PROPS_SPORTS) — no alert sent.")
        return
    setup_props_table()

    if date_override:
        try:
            datetime.strptime(date_override, "%Y-%m-%d")
            date_str = date_override
        except ValueError:
            print(f"ERROR: --date must be YYYY-MM-DD, got '{date_override}'")
            sys.exit(1)
    else:
        date_str = str(get_today_ct())
    print(f"Building props alert for {date_str}...")

    props = fetch_today_props(date_str)
    fades = fetch_fade_props(date_str)
    if not props and not fades:
        print(f"No projection-green OVER on {ALLOWED_STATS} with edge >= {MIN_EDGE_PCT}% today. No alert sent.")
        return
    print(f"  {len(props)} pick(s) selected (max {MAX_PICKS})")

    message = build_message(date_str, props, fades)
    print("\n" + "\u2500" * 40)
    print(message)
    print("\u2500" * 40 + "\n")

    if dry_run:
        print("DRY RUN — not sent.")
        return

    send_message(message)
    time.sleep(2)  # match existing alert pacing


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print message without sending to Telegram")
    parser.add_argument("--date", metavar="YYYY-MM-DD", help="Preview alert for a specific date instead of today")
    args = parser.parse_args()
    run(dry_run=args.dry_run, date_override=args.date)
