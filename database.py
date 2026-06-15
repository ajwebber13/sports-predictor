"""
database.py — Culture & Pulse Analytics
Central SQLite database for team history, odds, predictions, and results.
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cp_analytics.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    c    = conn.cursor()

    # ── TEAM STATS (historical — 5 years) ──────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS team_stats (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sport           TEXT NOT NULL,
            season          TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            wins            INTEGER DEFAULT 0,
            losses          INTEGER DEFAULT 0,
            pts_per_game    REAL DEFAULT 0,
            pts_allowed     REAL DEFAULT 0,
            net_rating      REAL DEFAULT 0,
            off_rating      REAL DEFAULT 0,
            def_rating      REAL DEFAULT 0,
            pace            REAL DEFAULT 0,
            home_wins       INTEGER DEFAULT 0,
            home_losses     INTEGER DEFAULT 0,
            away_wins       INTEGER DEFAULT 0,
            away_losses     INTEGER DEFAULT 0,
            last_10_wins    INTEGER DEFAULT 0,
            rest_days_avg   REAL DEFAULT 0,
            source          TEXT DEFAULT 'manual',
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sport, season, team_name)
        )
    """)

    # ── ODDS HISTORY (your own odds database) ──────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS odds_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            sport           TEXT NOT NULL,
            home_team       TEXT NOT NULL,
            away_team       TEXT NOT NULL,
            home_ml         INTEGER,
            away_ml         INTEGER,
            home_implied    REAL,
            away_implied    REAL,
            spread          REAL,
            over_under      REAL,
            opening_home_ml INTEGER,
            opening_away_ml INTEGER,
            closing_home_ml INTEGER,
            closing_away_ml INTEGER,
            source          TEXT DEFAULT 'espn',
            captured_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport, home_team, away_team)
        )
    """)

    # ── PREDICTIONS (replaces JSON files) ──────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            sport           TEXT NOT NULL,
            game            TEXT NOT NULL,
            home_team       TEXT NOT NULL,
            away_team       TEXT NOT NULL,
            bet             TEXT NOT NULL,
            odds            INTEGER,
            model_prob      REAL,
            implied_prob    REAL,
            edge            REAL,
            home_record     TEXT,
            away_record     TEXT,
            home_rest       INTEGER,
            away_rest       INTEGER,
            home_injuries   TEXT,
            away_injuries   TEXT,
            game_type       TEXT DEFAULT 'regular_season',
            predicted_winner TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport, game, bet)
        )
    """)

    # ── RESULTS (actual outcomes for model tracking) ────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            sport           TEXT NOT NULL,
            game            TEXT NOT NULL,
            home_team       TEXT NOT NULL,
            away_team       TEXT NOT NULL,
            home_score      INTEGER,
            away_score      INTEGER,
            actual_winner   TEXT,
            prediction_id   INTEGER REFERENCES predictions(id),
            correct         INTEGER,
            edge_at_pick    REAL,
            odds_at_pick    INTEGER,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport, game)
        )
    """)

    # ── HEAD TO HEAD (historical matchup data) ──────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS head_to_head (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sport           TEXT NOT NULL,
            season          TEXT NOT NULL,
            date            TEXT NOT NULL,
            home_team       TEXT NOT NULL,
            away_team       TEXT NOT NULL,
            home_score      INTEGER,
            away_score      INTEGER,
            winner          TEXT,
            game_type       TEXT DEFAULT 'regular_season',
            source          TEXT DEFAULT 'manual',
            UNIQUE(sport, date, home_team, away_team)
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialized: cp_analytics.db")
    print("Tables created: team_stats, odds_history, predictions, results, head_to_head")


# ── ODDS LOGGING ────────────────────────────────────────────────────────

def log_odds(sport: str, games: list, source: str = "espn"):
    """
    Call this every morning after get_live_odds() runs.
    Saves today's lines to odds_history automatically.
    """
    from services.odds_parser import american_to_implied

    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    saved = 0

    for game in games:
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        home_ml   = None
        away_ml   = None

        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market["key"] == "h2h":
                    for o in market.get("outcomes", []):
                        if o["name"] == home_team:
                            home_ml = o["price"]
                        elif o["name"] == away_team:
                            away_ml = o["price"]

        if not home_ml or not away_ml:
            continue

        home_implied = round(american_to_implied(home_ml) * 100, 1)
        away_implied = round(american_to_implied(away_ml) * 100, 1)

        try:
            c.execute("""
                INSERT OR IGNORE INTO odds_history
                (date, sport, home_team, away_team, home_ml, away_ml,
                 home_implied, away_implied, source, opening_home_ml, opening_away_ml)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (today, sport, home_team, away_team, home_ml, away_ml,
                  home_implied, away_implied, source, home_ml, away_ml))
            saved += 1
        except Exception as e:
            print(f"Odds log error: {e}")

    conn.commit()
    conn.close()
    print(f"Logged {saved} games to odds_history ({sport})")


def update_closing_odds(sport: str, games: list):
    """
    Call this at noon to capture closing line movement.
    Compares to opening line stored this morning.
    """
    from services.odds_parser import american_to_implied

    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")

    for game in games:
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        home_ml   = None
        away_ml   = None

        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market["key"] == "h2h":
                    for o in market.get("outcomes", []):
                        if o["name"] == home_team:
                            home_ml = o["price"]
                        elif o["name"] == away_team:
                            away_ml = o["price"]

        if not home_ml or not away_ml:
            continue

        c.execute("""
            UPDATE odds_history
            SET closing_home_ml = ?,
                closing_away_ml = ?
            WHERE date = ? AND sport = ?
            AND home_team = ? AND away_team = ?
        """, (home_ml, away_ml, today, sport, home_team, away_team))

    conn.commit()
    conn.close()
    print(f"Updated closing lines for {sport}")


# ── PREDICTION LOGGING ──────────────────────────────────────────────────

def log_prediction(bet: dict, sport: str):
    """Save a prediction to the DB. Replaces prediction_logger.py JSON saves."""
    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    game  = bet.get("game", "")
    parts = game.split(" @ ")

    try:
        c.execute("""
            INSERT OR IGNORE INTO predictions
            (date, sport, game, home_team, away_team, bet, odds,
             model_prob, implied_prob, edge, home_record, away_record,
             home_rest, away_rest, home_injuries, away_injuries, predicted_winner)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            today, sport, game,
            parts[1] if len(parts) == 2 else "",
            parts[0] if len(parts) == 2 else "",
            bet.get("bet", ""),
            bet.get("odds"),
            bet.get("model_prob", 0),
            bet.get("implied_prob", 0),
            round(bet.get("edge", 0) * 100, 2),
            bet.get("home_record", ""),
            bet.get("away_record", ""),
            bet.get("home_rest"),
            bet.get("away_rest"),
            bet.get("home_injuries", ""),
            bet.get("away_injuries", ""),
            bet.get("bet", "").replace(" ML", ""),
        ))
        conn.commit()
        print(f"Logged prediction: {game}")
    except Exception as e:
        print(f"Prediction log error: {e}")
    finally:
        conn.close()


# ── RESULTS LOGGING ─────────────────────────────────────────────────────

def log_result(sport: str, game: str, date: str,
               home_score: int, away_score: int):
    """Log actual game result and auto-score the prediction."""
    conn  = get_conn()
    c     = conn.cursor()
    parts = game.split(" @ ")
    home  = parts[1] if len(parts) == 2 else ""
    away  = parts[0] if len(parts) == 2 else ""

    actual_winner = home if home_score > away_score else away

    # Find matching prediction
    c.execute("""
        SELECT id, predicted_winner, edge, odds
        FROM predictions
        WHERE date = ? AND sport = ? AND game = ?
    """, (date, sport, game))
    pred = c.fetchone()

    correct      = None
    pred_id      = None
    edge_at_pick = None
    odds_at_pick = None

    if pred:
        pred_id      = pred["id"]
        edge_at_pick = pred["edge"]
        odds_at_pick = pred["odds"]
        correct      = 1 if pred["predicted_winner"] == actual_winner else 0

    try:
        c.execute("""
            INSERT OR REPLACE INTO results
            (date, sport, game, home_team, away_team,
             home_score, away_score, actual_winner,
             prediction_id, correct, edge_at_pick, odds_at_pick)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, sport, game, home, away,
              home_score, away_score, actual_winner,
              pred_id, correct, edge_at_pick, odds_at_pick))
        conn.commit()

        status = "✅ CORRECT" if correct == 1 else "❌ WRONG" if correct == 0 else "⚪ NO PICK"
        print(f"Result logged: {game} — {actual_winner} wins {status}")
    except Exception as e:
        print(f"Result log error: {e}")
    finally:
        conn.close()


# ── MODEL REPORT ────────────────────────────────────────────────────────

def model_report(sport: str = None):
    """Print win rate and ROI by sport."""
    conn = get_conn()
    c    = conn.cursor()

    query = """
        SELECT sport,
               COUNT(*) as picks,
               SUM(correct) as wins,
               ROUND(AVG(correct) * 100, 1) as win_rate,
               ROUND(AVG(edge_at_pick), 1) as avg_edge
        FROM results
        WHERE correct IS NOT NULL
    """
    params = []
    if sport:
        query  += " AND sport = ?"
        params.append(sport)

    query += " GROUP BY sport ORDER BY win_rate DESC"
    c.execute(query, params)
    rows = c.fetchall()

    print("\n📊 MODEL PERFORMANCE REPORT")
    print("─" * 45)
    for row in rows:
        print(f"{row['sport'].upper():<8} "
              f"Picks: {row['picks']:<5} "
              f"Wins: {row['wins']:<5} "
              f"Win Rate: {row['win_rate']}% "
              f"Avg Edge: {row['avg_edge']}%")
    print("─" * 45)
    conn.close()


if __name__ == "__main__":
    init_db()
    model_report()