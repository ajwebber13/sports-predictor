"""
hbcu_predict.py - Culture & Pulse Analytics
Prediction engine for HBCU sports (MEAC/SWAC).

Since no betting odds exist for HBCU games, this engine outputs
pure model-based win probabilities and team strength ratings
rather than betting edge signals. Think power rankings + game
previews rather than betting picks.

Sources: ESPN team schedule endpoint (upcoming games 7 days out)
Models:  Elo ratings + advanced metrics + ensemble ML

Usage:
  python hbcu_predict.py football
  python hbcu_predict.py mbb
  python hbcu_predict.py wbb
  python hbcu_predict.py all
"""

import requests
import time
from datetime import datetime, timedelta
from database import get_conn
from hbcu_teams import HBCU_FOOTBALL_TEAMS, HBCU_MBB_TEAMS, HBCU_WBB_TEAMS
from hbcu_rivalries import get_rivalry_context

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

SPORT_CONFIGS = {
    "hbcu_football": {
        "label":     "HBCU Football",
        "emoji":     "🏈",
        "path":      "football/college-football",
        "registry":  HBCU_FOOTBALL_TEAMS,
        "adv_sport": "hbcu_football",
    },
    "hbcu_mbb": {
        "label":     "HBCU Men's Basketball",
        "emoji":     "🏀",
        "path":      "basketball/mens-college-basketball",
        "registry":  HBCU_MBB_TEAMS,
        "adv_sport": "hbcu_mbb",
    },
    "hbcu_wbb": {
        "label":     "HBCU Women's Basketball",
        "emoji":     "🏀",
        "path":      "basketball/womens-college-basketball",
        "registry":  HBCU_WBB_TEAMS,
        "adv_sport": "hbcu_wbb",
    },
}


def get_upcoming_games(sport_key: str, days_ahead: int = 7) -> list:
    """
    Pulls upcoming games for all HBCU teams in a sport
    within the next N days. Deduplicates so each game
    only appears once even if both teams are in our registry.
    """
    config   = SPORT_CONFIGS[sport_key]
    registry = config["registry"]
    path     = config["path"]
    today    = datetime.now().date()
    cutoff   = today + timedelta(days=days_ahead)

    seen_games = set()
    upcoming   = []

    for team_name, info in registry.items():
        team_id = info["id"]
        url = f"https://site.api.espn.com/apis/site/v2/sports/{path}/teams/{team_id}/schedule"

        try:
            r    = requests.get(url, headers=HEADERS, timeout=10)
            data = r.json()
        except Exception:
            continue

        for event in data.get("events", []):
            date_str = event.get("date", "")[:10]
            try:
                game_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            if not (today <= game_date <= cutoff):
                continue

            comps = event.get("competitions", [])
            if not comps:
                continue
            comp = comps[0]

            status = comp.get("status", {}).get("type", {})
            if status.get("completed"):
                continue

            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), None)
            away = next((c for c in competitors if c.get("homeAway") == "away"), None)
            if not home or not away:
                continue

            home_name = home.get("team", {}).get("displayName", "")
            away_name = away.get("team", {}).get("displayName", "")

            game_key = tuple(sorted([home_name, away_name]) + [date_str])
            if game_key in seen_games:
                continue
            seen_games.add(game_key)

            upcoming.append({
                "home_team": home_name,
                "away_team": away_name,
                "date":      date_str,
                "event_id":  event.get("id", ""),
            })

        time.sleep(0.2)

    return upcoming


def get_elo(team_name: str, sport_key: str) -> float:
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT elo FROM elo_ratings
        WHERE sport = ? AND team_name = ?
    """, (sport_key, team_name))
    row = c.fetchone()
    conn.close()
    return row["elo"] if row else 1500.0


def get_adv_metrics(team_name: str, sport_key: str) -> dict:
    conn = get_conn()
    c    = conn.cursor()
    c.execute("""
        SELECT off_rating, def_rating, net_rating
        FROM advanced_metrics
        WHERE sport = ? AND team_name = ?
        ORDER BY season DESC LIMIT 1
    """, (sport_key, team_name))
    row = c.fetchone()
    conn.close()
    if row:
        return {"off": row["off_rating"], "def": row["def_rating"], "net": row["net_rating"]}
    return {"off": 0.0, "def": 0.0, "net": 0.0}


def predict_game(home_team: str, away_team: str, sport_key: str) -> dict:
    """
    Combines Elo + advanced metrics + ensemble ML into a
    final win probability for each team.
    """
    home_elo = get_elo(home_team, sport_key)
    away_elo = get_elo(away_team, sport_key)

    elo_diff      = home_elo - away_elo
    home_elo_prob = 1 / (1 + 10 ** (-elo_diff / 400))
    away_elo_prob = 1 - home_elo_prob

    home_adv = get_adv_metrics(home_team, sport_key)
    away_adv = get_adv_metrics(away_team, sport_key)

    net_diff      = home_adv["net"] - away_adv["net"]
    adv_home_prob = round(0.5 + (net_diff * 0.015), 3)
    adv_home_prob = min(max(adv_home_prob, 0.1), 0.9)
    adv_away_prob = 1 - adv_home_prob

    home_prob = round((home_elo_prob * 0.5) + (adv_home_prob * 0.5), 3)
    away_prob = round(1 - home_prob, 3)

    try:
        from ensemble_model import predict_game as ens_predict
        ens = ens_predict(home_team, away_team, sport_key)
        if ens and ens.get("ensemble_home_prob"):
            ens_home  = ens["ensemble_home_prob"] / 100
            home_prob = round((home_prob * 0.6) + (ens_home * 0.4), 3)
            away_prob = round(1 - home_prob, 3)
    except Exception:
        pass

    home_conf = get_conference(home_team, sport_key)
    away_conf = get_conference(away_team, sport_key)

    return {
        "home_team":  home_team,
        "away_team":  away_team,
        "home_prob":  round(home_prob * 100, 1),
        "away_prob":  round(away_prob * 100, 1),
        "home_elo":   round(home_elo, 1),
        "away_elo":   round(away_elo, 1),
        "home_net":   home_adv["net"],
        "away_net":   away_adv["net"],
        "home_conf":  home_conf,
        "away_conf":  away_conf,
        "favorite":   home_team if home_prob >= 0.5 else away_team,
        "confidence": round(max(home_prob, away_prob) * 100, 1),
    }


def get_conference(team_name: str, sport_key: str) -> str:
    from hbcu_teams import get_team_registry
    registry = get_team_registry(sport_key)
    info     = registry.get(team_name)
    return info["conf"] if info else ""


def format_alert(pred: dict, game_date: str, sport_key: str) -> str:
    config   = SPORT_CONFIGS[sport_key]
    emoji    = config["emoji"]
    label    = config["label"]
    home     = pred["home_team"]
    away     = pred["away_team"]
    fav      = pred["favorite"]
    conf     = round(pred["confidence"], 1)

    home_conf_tag = f" ({pred['home_conf']})" if pred["home_conf"] else ""
    away_conf_tag = f" ({pred['away_conf']})" if pred["away_conf"] else ""
    stars = "★★★" if conf >= 70 else "★★" if conf >= 60 else "★"

    # ── Rivalry context ──
    rivalry_block = ""
    try:
        ctx = get_rivalry_context(home, away, sport_key)
        if ctx:
            rivalry_block = ctx["telegram_block"]
    except Exception:
        pass

    alert = (
        f"{emoji} <b>{label.upper()} — GAME PREVIEW</b>\n\n"
        f"<b>{away}{away_conf_tag} @ {home}{home_conf_tag}</b>\n"
        f"📅 {game_date}\n\n"
        f"🏆 <b>Model Favorite: {fav} {stars}</b>\n\n"
        f"<b>WIN PROBABILITY</b>\n"
        f"{home}: {pred['home_prob']}%\n"
        f"{away}: {pred['away_prob']}%\n\n"
        f"<b>ELO RATINGS</b>\n"
        f"{home}: {pred['home_elo']}\n"
        f"{away}: {pred['away_elo']}\n\n"
        f"<b>NET RATING</b>\n"
        f"{home}: {pred['home_net']:+.1f}\n"
        f"{away}: {pred['away_net']:+.1f}"
    )

    if rivalry_block:
        alert += f"\n{rivalry_block}"

    alert += (
        f"\n{'─' * 24}\n"
        f"<i>Culture &amp; Pulse Analytics\n"
        f"For entertainment only.</i>"
    )

    return alert


def run_hbcu_sport(sport_key: str, send_telegram: bool = False):
    config = SPORT_CONFIGS[sport_key]
    label  = config["label"]

    print(f"\n{'='*60}")
    print(f"  {label.upper()} PREDICTIONS")
    print(f"  {datetime.now().strftime('%A, %B %d %Y')}")
    print(f"{'='*60}")

    games = get_upcoming_games(sport_key)

    if not games:
        print(f"  No upcoming {label} games found in the next 7 days.")
        return []

    print(f"  {len(games)} upcoming game(s) found\n")

    predictions = []
    for game in games:
        pred  = predict_game(game["home_team"], game["away_team"], sport_key)
        alert = format_alert(pred, game["date"], sport_key)
        print(alert)
        print()

        if send_telegram:
            try:
                from telegram_alerts import send_message
                send_message(alert)
                time.sleep(1)
            except Exception as e:
                print(f"  Telegram error: {e}")

        predictions.append({**pred, "date": game["date"]})

    return predictions


if __name__ == "__main__":
    import sys

    send_tg = "--telegram" in sys.argv

    if len(sys.argv) > 1 and sys.argv[1] not in ("--telegram",):
        arg = sys.argv[1].lower()
        if arg == "football":
            run_hbcu_sport("hbcu_football", send_telegram=send_tg)
        elif arg == "mbb":
            run_hbcu_sport("hbcu_mbb", send_telegram=send_tg)
        elif arg == "wbb":
            run_hbcu_sport("hbcu_wbb", send_telegram=send_tg)
        elif arg == "all":
            run_hbcu_sport("hbcu_football", send_telegram=send_tg)
            run_hbcu_sport("hbcu_mbb",      send_telegram=send_tg)
            run_hbcu_sport("hbcu_wbb",      send_telegram=send_tg)
        else:
            print(f"Unknown sport: {arg}")
            print("Usage: python hbcu_predict.py [football|mbb|wbb|all] [--telegram]")
    else:
        print("Usage: python hbcu_predict.py [football|mbb|wbb|all] [--telegram]")
        print("  --telegram   Send predictions to Telegram channel")