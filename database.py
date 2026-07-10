"""
database.py - Culture & Pulse Sports Analytics

Central database connection and schema management.

Supports:
- Turso libSQL (production)
- SQLite fallback (local development)
"""

import sqlite3
import os
import tempfile


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(
    BASE_DIR,
    "cp_analytics.db"
)


TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_conn():

    if TURSO_URL and TURSO_TOKEN:

        import libsql

        replica = os.path.join(
            tempfile.gettempdir(),
            "cp_analytics_replica.db"
        )

        conn = libsql.connect(
            replica,
            sync_url=TURSO_URL,
            auth_token=TURSO_TOKEN
        )

        try:
            conn.sync()
        except Exception as e:
            print(
                f"Turso sync warning: {e}"
            )

        return conn


    conn = sqlite3.connect(
        DB_PATH
    )

    conn.row_factory = sqlite3.Row

    return conn



# --------------------------------------------------
# DATABASE INITIALIZATION
# --------------------------------------------------

def init_db():

    conn = get_conn()

    c = conn.cursor()


    # ----------------------------
    # TEAM DATA
    # ----------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS team_stats (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        sport TEXT NOT NULL,
        season TEXT NOT NULL,
        team_name TEXT NOT NULL,

        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,

        points_for REAL DEFAULT 0,
        points_against REAL DEFAULT 0,

        offensive_rating REAL DEFAULT 0,
        defensive_rating REAL DEFAULT 0,

        pace REAL DEFAULT 0,

        source TEXT DEFAULT 'manual',

        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,


        UNIQUE(
            sport,
            season,
            team_name
        )

    )
    """)



    # ----------------------------
    # ODDS
    # ----------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS odds_history (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        date TEXT NOT NULL,

        sport TEXT NOT NULL,

        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,


        home_ml INTEGER,
        away_ml INTEGER,

        spread REAL,

        over_under REAL,


        opening_home_ml INTEGER,
        opening_away_ml INTEGER,

        closing_home_ml INTEGER,
        closing_away_ml INTEGER,


        source TEXT DEFAULT 'api',

        created_at TEXT DEFAULT CURRENT_TIMESTAMP,


        UNIQUE(
            date,
            sport,
            home_team,
            away_team
        )

    )
    """)



    # ----------------------------
    # PREDICTIONS
    # ----------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS predictions (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        date TEXT NOT NULL,

        sport TEXT NOT NULL,

        game TEXT NOT NULL,


        home_team TEXT,

        away_team TEXT,


        prediction TEXT,


        odds INTEGER,


        model_probability REAL,

        implied_probability REAL,

        edge REAL,


        confidence REAL,


        created_at TEXT DEFAULT CURRENT_TIMESTAMP,


        UNIQUE(
            date,
            sport,
            game
        )

    )
    """)



    # ----------------------------
    # RESULTS
    # ----------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS results (

        id INTEGER PRIMARY KEY AUTOINCREMENT,


        date TEXT NOT NULL,

        sport TEXT NOT NULL,

        game TEXT NOT NULL,


        home_score INTEGER,

        away_score INTEGER,


        winner TEXT,


        prediction_id INTEGER,


        correct INTEGER,


        created_at TEXT DEFAULT CURRENT_TIMESTAMP

    )
    """)



    # ----------------------------
    # PLAYER PROPS
    # ----------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS player_props (

        id INTEGER PRIMARY KEY AUTOINCREMENT,


        date TEXT,

        sport TEXT,


        player_name TEXT,

        team TEXT,


        prop TEXT,


        line REAL,


        projection REAL,


        edge REAL,


        confidence REAL,


        result TEXT,


        created_at TEXT DEFAULT CURRENT_TIMESTAMP

    )
    """)



    # ----------------------------
    # BANKROLL TRACKING
    # ----------------------------

    c.execute("""
    CREATE TABLE IF NOT EXISTS bankroll (

        id INTEGER PRIMARY KEY AUTOINCREMENT,


        date TEXT,

        sport TEXT,

        game TEXT,


        bet TEXT,


        odds INTEGER,


        stake REAL,


        profit_loss REAL,


        bankroll REAL,


        result TEXT

    )
    """)



    conn.commit()

    conn.close()


    print(
        "Database initialized successfully"
    )



# --------------------------------------------------
# TEST
# --------------------------------------------------

if __name__ == "__main__":

    init_db()