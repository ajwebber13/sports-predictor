"""
database.py - Culture & Pulse Analytics
Central database for team history, odds, predictions, and results.

Backed by Turso (hosted libSQL) in production so data survives across
Render's ephemeral cron containers. Falls back to a local SQLite file
when TURSO_DATABASE_URL / TURSO_AUTH_TOKEN aren't set (local dev).
"""

import sqlite3
import os
import tempfile
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cp_analytics.db")

TURSO_URL   = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


class _Row:
    """Dict-and-index accessible row, drop-in replacement for sqlite3.Row
    so existing code using row['col'] or dict(row) keeps working against
    libsql, which only returns plain tuples."""
    def __init__(self, cols, values):
        self._cols = cols
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._cols.index(key)]
        return self._values[key]

    def keys(self):
        return list(self._cols)

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return repr(dict(zip(self._cols, self._values)))


def _as_tuple(params):
    if params is None:
        return ()
    if isinstance(params, list):
        return tuple(params)
    return params


class _CursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def _cols(self):
        return [d[0] for d in (self._cursor.description or [])]

    def execute(self, sql, params=None):
        self._cursor.execute(sql, _as_tuple(params))
        return self

    def executemany(self, sql, seq_of_params):
        self._cursor.executemany(sql, [_as_tuple(p) for p in seq_of_params])
        return self

    def executescript(self, sql):
        self._cursor.executescript(sql)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _Row(self._cols(), row)

    def fetchall(self):
        cols = self._cols()
        return [_Row(cols, r) for r in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def description(self):
        return self._cursor.description


class _ConnWrapper:
    """Wraps a libsql connection so it behaves like sqlite3.Connection
    (row_factory-style dict access, tuple-safe params, .sync() on commit)."""
    def __init__(self, conn):
        self._conn = conn
        self.row_factory = None  # accepted for API compat, ignored

    def execute(self, sql, params=None):
        cur = _CursorWrapper(self._conn.cursor())
        return cur.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        cur = _CursorWrapper(self._conn.cursor())
        return cur.executemany(sql, seq_of_params)

    def executescript(self, sql):
        cur = _CursorWrapper(self._conn.cursor())
        return cur.executescript(sql)

    def cursor(self):
        return _CursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()
        try:
            self._conn.sync()
        except Exception as e:
            print(f"Turso sync warning: {e}")

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_conn():
    if TURSO_URL and TURSO_TOKEN:
        import libsql
        local_replica = os.path.join(tempfile.gettempdir(), "cp_analytics_replica.db")
        conn = libsql.connect(
            local_replica,
            sync_url=TURSO_URL,
            auth_token=TURSO_TOKEN,
        )
        try:
            conn.sync()
        except Exception as e:
            print(f"Turso initial sync warning: {e}")
        return _ConnWrapper(conn)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c    = conn.cursor()

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
            UNIQUE(date, sport, game)
        )
    """)

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
            ga