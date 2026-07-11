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


# .strip() guards against invisible characters (stray \r, \n, trailing
# space) riding along in the env var value from however it was
# originally set — GUI paste, a .env file with CRLF line endings, etc.
# A control character in an HTTP header value throws exactly the kind
# of "invalid auth header: failed to parse header value" error this
# was added to fix; same category of bug as the whitespace issue
# already fixed in nfl_player_game_logs.py's date arguments.
TURSO_URL = (os.environ.get("TURSO_DATABASE_URL") or "").strip()
TURSO_TOKEN = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()


class _Row:
    """Mimics sqlite3.Row: supports BOTH row["col"] and row[0] access,
    plus .keys() so dict(row) works, plus iteration so rows_to_dicts()
    below still works unchanged on these too.

    Why this exists: the local-SQLite fallback branch below already
    gets this behavior via conn.row_factory = sqlite3.Row. The Turso/
    libsql branch never had an equivalent, so libsql's plain-tuple rows
    silently broke every dict(row) / row["col"] call site in the
    codebase the moment a query actually ran against Turso instead of
    local SQLite — dozens of files (elo_ratings.py, ensemble_model.py,
    every sport's predictor, render_job.py, recap_engine.py,
    prop_tracker.py, auto_results.py, and more) all assume this access
    pattern. Wrapping the connection here fixes all of them at the
    source instead of patching each file individually."""
    __slots__ = ("_columns", "_values")

    def __init__(self, columns, values):
        self._columns = columns
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                idx = self._columns.index(key)
            except ValueError:
                raise KeyError(key)
            return self._values[idx]
        return self._values[key]

    def keys(self):
        return list(self._columns)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return f"Row({dict(zip(self._columns, self._values))})"


class _DictCursorWrapper:
    """Wraps a libsql cursor so fetchone()/fetchall() return _Row
    objects instead of plain tuples. Everything else (execute,
    rowcount, lastrowid, description, close, ...) passes straight
    through to the real cursor via __getattr__."""

    def __init__(self, real_cursor):
        self._cursor = real_cursor

    def execute(self, *args, **kwargs):
        self._cursor.execute(*args, **kwargs)
        return self

    def executemany(self, *args, **kwargs):
        self._cursor.executemany(*args, **kwargs)
        return self

    def _columns(self):
        return [d[0] for d in self._cursor.description] if self._cursor.description else []

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _Row(self._columns(), row)

    def fetchall(self):
        cols = self._columns()
        return [_Row(cols, r) for r in self._cursor.fetchall()]

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _DictConnWrapper:
    """Wraps a libsql connection so both conn.cursor() and the direct
    conn.execute() shortcut (used in Turso's own docs) return
    dict-row-capable cursors. commit/close/sync/rollback/etc. pass
    straight through to the real connection via __getattr__."""

    def __init__(self, real_conn):
        self._conn = real_conn

    def cursor(self):
        return _DictCursorWrapper(self._conn.cursor())

    def execute(self, *args, **kwargs):
        real_cursor = self._conn.execute(*args, **kwargs)
        return _DictCursorWrapper(real_cursor)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def rows_to_dicts(cursor, rows):
    """Converts cursor.fetchall()/fetchone() rows into plain dicts using
    cursor.description column names, instead of calling dict(row) on the
    row objects directly.

    Why this exists: dict(row) only works when row has a .keys() method
    (sqlite3.Row supports this when conn.row_factory = sqlite3.Row is
    set, which the local-SQLite branch of get_conn() below does). The
    Turso/libsql branch never set an equivalent row factory, and the
    libsql package apparently returns plain tuples — dict(tuple) then
    fails with "dictionary update sequence element #0 has length N" the
    moment it tries to treat the first column's value as a (key, value)
    pair. This bit nfl_projections.py first, but the identical dict(r)
    pattern also exists in star_players.py, wnba/mlb/nba_projections.py,
    and wnba/mlb/nba_defense_ratings.py — those may be silently broken
    against production Turso too since the libsql-experimental -> libsql
    package swap. Building the dict from cursor.description explicitly
    works the same way regardless of what row type either package
    returns, so it's not vulnerable to this class of bug going forward."""
    if rows is None:
        return []
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in rows]


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

        return _DictConnWrapper(conn)


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
