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
        import libsql_experimental as libsql
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
            game_type       TEXT DEFAULT 'regular_season',
            source          TEXT DEFAULT 'manual',
            UNIQUE(sport, date, home_team, away_team)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS line_movement (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            sport           TEXT NOT NULL,
            home_team       TEXT NOT NULL,
            away_team       TEXT NOT NULL,
            opening_home_ml INTEGER,
            opening_away_ml INTEGER,
            closing_home_ml INTEGER,
            closing_away_ml INTEGER,
            movement_home   INTEGER,
            movement_away   INTEGER,
            sharp_signal    TEXT,
            captured_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport, home_team, away_team)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS injuries_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            sport           TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            player_name     TEXT NOT NULL,
            status          TEXT NOT NULL,
            position        TEXT DEFAULT '',
            impact          REAL DEFAULT 0.0,
            captured_at     TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport, team_name, player_name)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS advanced_metrics (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sport           TEXT NOT NULL,
            season          TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            off_rating      REAL DEFAULT 0.0,
            def_rating      REAL DEFAULT 0.0,
            net_rating      REAL DEFAULT 0.0,
            pace            REAL DEFAULT 0.0,
            ts_pct          REAL DEFAULT 0.0,
            reb_pct         REAL DEFAULT 0.0,
            ast_pct         REAL DEFAULT 0.0,
            tov_pct         REAL DEFAULT 0.0,
            source          TEXT DEFAULT 'espn',
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(sport, season, team_name)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS bankroll_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            sport           TEXT NOT NULL,
            game            TEXT NOT NULL,
            bet             TEXT NOT NULL,
            odds            INTEGER,
            stake           REAL NOT NULL,
            result          TEXT,
            profit_loss     REAL DEFAULT 0.0,
            bankroll_after  REAL DEFAULT 0.0,
            edge_at_pick    REAL,
            notes           TEXT DEFAULT '',
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS situational_factors (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            date                TEXT NOT NULL,
            sport               TEXT NOT NULL,
            home_team           TEXT NOT NULL,
            away_team           TEXT NOT NULL,
            away_miles_traveled REAL DEFAULT 0.0,
            away_time_zones     INTEGER DEFAULT 0,
            home_altitude_ft    INTEGER DEFAULT 0,
            away_road_game_num  INTEGER DEFAULT 0,
            away_back_to_back   INTEGER DEFAULT 0,
            home_back_to_back   INTEGER DEFAULT 0,
            away_rest_days      INTEGER DEFAULT 1,
            home_rest_days      INTEGER DEFAULT 1,
            altitude_adj        REAL DEFAULT 0.0,
            travel_adj          REAL DEFAULT 0.0,
            total_adj           REAL DEFAULT 0.0,
            captured_at         TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, sport, home_team, away_team)
        )
    """)

    conn.commit()
    conn.close()
    print("Database initialized: cp_analytics.db")
    print("Tables created: team_stats, odds_history, predictions, results,")
    print("                head_to_head, line_movement, injuries_log,")
    print("                advanced_metrics, bankroll_log, situational_factors")


def log_odds(sport: str, games: list, source: str = "espn"):
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


def log_line_movement(sport: str, games: list):
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

        c.execute("""
            SELECT opening_home_ml, opening_away_ml
            FROM odds_history
            WHERE date = ? AND sport = ?
            AND home_team = ? AND away_team = ?
        """, (today, sport, home_team, away_team))
        row = c.fetchone()

        if not row:
            continue

        opening_home = row["opening_home_ml"]
        opening_away = row["opening_away_ml"]

        if not opening_home or not opening_away:
            continue

        movement_home = home_ml - opening_home
        movement_away = away_ml - opening_away

        sharp = None
        if abs(movement_home) >= 10:
            direction = "shorter" if home_ml < opening_home else "longer"
            sharp = f"HOME line moved {movement_home} pts ({direction}) - possible sharp action"
        elif abs(movement_away) >= 10:
            direction = "shorter" if away_ml < opening_away else "longer"
            sharp = f"AWAY line moved {movement_away} pts ({direction}) - possible sharp action"

        try:
            c.execute("""
                INSERT OR REPLACE INTO line_movement
                (date, sport, home_team, away_team,
                 opening_home_ml, opening_away_ml,
                 closing_home_ml, closing_away_ml,
                 movement_home, movement_away, sharp_signal)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (today, sport, home_team, away_team,
                  opening_home, opening_away,
                  home_ml, away_ml,
                  movement_home, movement_away, sharp))
            saved += 1

            if sharp:
                print(f"  SHARP: {sharp} - {away_team} @ {home_team}")

        except Exception as e:
            print(f"Line movement log error: {e}")

    conn.commit()
    conn.close()
    print(f"Line movement logged: {saved} games ({sport})")


def log_injuries(sport: str):
    try:
        from injury_check import get_injuries
        injuries = get_injuries(sport)
    except Exception as e:
        print(f"Injury fetch error: {e}")
        return

    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    saved = 0

    for team_name, players in injuries.items():
        if not team_name:
            continue
        for player_str in players:
            try:
                if "(" in player_str:
                    player_name = player_str.split("(")[0].strip()
                    status      = player_str.split("(")[1].replace(")", "").strip()
                else:
                    player_name = player_str
                    status      = "Unknown"

                c.execute("""
                    INSERT OR IGNORE INTO injuries_log
                    (date, sport, team_name, player_name, status)
                    VALUES (?, ?, ?, ?, ?)
                """, (today, sport, team_name, player_name, status))
                saved += 1
            except Exception as e:
                print(f"Injury log error: {e}")

    conn.commit()
    conn.close()
    print(f"Logged {saved} injury records ({sport})")


def log_bankroll(date: str, sport: str, game: str, bet: str,
                 odds: int, stake: float, result: str,
                 profit_loss: float, bankroll_after: float,
                 edge: float = 0.0, notes: str = ""):
    conn = get_conn()
    c    = conn.cursor()

    try:
        c.execute("""
            INSERT INTO bankroll_log
            (date, sport, game, bet, odds, stake, result,
             profit_loss, bankroll_after, edge_at_pick, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (date, sport, game, bet, odds, stake, result,
              profit_loss, bankroll_after, edge, notes))
        conn.commit()
        status = "WIN" if result == "win" else "LOSS"
        print(f"Bankroll logged: {status} {game} | P/L: ${profit_loss} | Balance: ${bankroll_after}")
    except Exception as e:
        print(f"Bankroll log error: {e}")
    finally:
        conn.close()


def get_bankroll_summary():
    conn = get_conn()
    c    = conn.cursor()

    c.execute("""
        SELECT
            COUNT(*) as total_bets,
            SUM(CASE WHEN result = 'win' THEN 1 ELSE 0 END) as wins,
            SUM(profit_loss) as total_pl,
            MIN(bankroll_after) as lowest_balance,
            MAX(bankroll_after) as highest_balance,
            MIN(date) as first_bet,
            MAX(date) as last_bet
        FROM bankroll_log
    """)
    row = c.fetchone()

    c.execute("""
        SELECT sport,
               COUNT(*) as bets,
               SUM(profit_loss) as pl,
               ROUND(AVG(CASE WHEN result='win' THEN 1.0 ELSE 0.0 END)*100,1) as win_rate
        FROM bankroll_log
        GROUP BY sport
        ORDER BY pl DESC
    """)
    by_sport = c.fetchall()
    conn.close()

    if not row or not row["total_bets"]:
        print("\nNo bankroll data yet.")
        return

    total    = row["total_bets"]
    wins     = row["wins"] or 0
    pl       = round(row["total_pl"] or 0, 2)
    low      = row["lowest_balance"]
    high     = row["highest_balance"]
    first    = row["first_bet"]
    last     = row["last_bet"]
    win_rate = round(wins / total * 100, 1) if total > 0 else 0

    print(f"\n{'='*50}")
    print(f"  BANKROLL REPORT - Culture & Pulse")
    print(f"{'='*50}")
    print(f"  Record:    {wins}-{total-wins} ({win_rate}% win rate)")
    print(f"  Total P/L: ${pl}")
    print(f"  Peak:      ${high}")
    print(f"  Low:       ${low}")
    print(f"  Period:    {first} to {last}")

    if by_sport:
        print(f"\n  BY SPORT")
        print(f"  {'─'*35}")
        for s in by_sport:
            pl_val = s['pl'] or 0
            pl_str = f"+${pl_val}" if pl_val >= 0 else f"-${abs(pl_val)}"
            print(f"  {s['sport'].upper():<10} {s['bets']} bets | {s['win_rate']}% | {pl_str}")

    print(f"{'='*50}\n")


def log_situational_factors(sport: str, games: list):
    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    saved = 0

    ALTITUDE_MAP = {
        "Denver Nuggets":        5280,
        "Utah Jazz":             4226,
        "Oklahoma City Thunder": 1200,
        "Phoenix Suns":          1086,
        "Dallas Mavericks":       430,
        "San Antonio Spurs":      650,
        "Las Vegas Aces":        2030,
        "Phoenix Mercury":       1086,
        "Denver Broncos":        5280,
        "Las Vegas Raiders":     2030,
        "Arizona Cardinals":     1086,
        "Kansas City Chiefs":     820,
        "Dallas Cowboys":         430,
        "Colorado":              5430,
        "Utah":                  4226,
        "BYU":                   4551,
        "Air Force":             6995,
        "Wyoming":               7220,
        "New Mexico":            5312,
        "Boise State":           2730,
        "Nevada":                4500,
        "UNLV":                  2030,
        "Arizona":               2389,
        "Arizona State":         1086,
        "Colorado Buffaloes":    5430,
        "Utah Utes":             4226,
        "BYU Cougars":           4551,
        "Air Force Falcons":     6995,
        "Wyoming Cowboys":       7220,
        "New Mexico Lobos":      5312,
        "Boise State Broncos":   2730,
        "Nevada Wolf Pack":      4500,
        "UNLV Runnin Rebels":    2030,
    }

    CITY_COORDS = {
        # NBA
        "Boston Celtics":          (42.37, -71.06),
        "Brooklyn Nets":           (40.68, -73.97),
        "New York Knicks":         (40.75, -73.99),
        "Philadelphia 76ers":      (39.90, -75.17),
        "Toronto Raptors":         (43.64, -79.38),
        "Chicago Bulls":           (41.88, -87.67),
        "Cleveland Cavaliers":     (41.50, -81.69),
        "Detroit Pistons":         (42.69, -83.24),
        "Indiana Pacers":          (39.76, -86.16),
        "Milwaukee Bucks":         (43.04, -87.92),
        "Atlanta Hawks":           (33.76, -84.40),
        "Charlotte Hornets":       (35.22, -80.84),
        "Miami Heat":              (25.78, -80.19),
        "Orlando Magic":           (28.54, -81.38),
        "Washington Wizards":      (38.90, -77.02),
        "Denver Nuggets":          (39.75, -104.99),
        "Minnesota Timberwolves":  (44.98, -93.27),
        "Oklahoma City Thunder":   (35.46, -97.51),
        "Portland Trail Blazers":  (45.53, -122.67),
        "Utah Jazz":               (40.77, -111.90),
        "Golden State Warriors":   (37.77, -122.39),
        "Los Angeles Clippers":    (34.04, -118.27),
        "Los Angeles Lakers":      (34.04, -118.27),
        "Phoenix Suns":            (33.44, -112.07),
        "Sacramento Kings":        (38.58, -121.50),
        "Dallas Mavericks":        (32.79, -96.81),
        "Houston Rockets":         (29.75, -95.36),
        "Memphis Grizzlies":       (35.14, -90.05),
        "New Orleans Pelicans":    (29.95, -90.08),
        "San Antonio Spurs":       (29.43, -98.44),
        # WNBA
        "Atlanta Dream":           (33.76, -84.40),
        "Chicago Sky":             (41.88, -87.67),
        "Connecticut Sun":         (41.63, -72.09),
        "Dallas Wings":            (32.79, -96.81),
        "Golden State Valkyries":  (37.77, -122.39),
        "Indiana Fever":           (39.76, -86.16),
        "Las Vegas Aces":          (36.10, -115.17),
        "Los Angeles Sparks":      (34.04, -118.27),
        "Minnesota Lynx":          (44.98, -93.27),
        "New York Liberty":        (40.75, -73.99),
        "Phoenix Mercury":         (33.44, -112.07),
        "Portland Fire":           (45.53, -122.67),
        "Seattle Storm":           (47.62, -122.35),
        "Toronto Tempo":           (43.64, -79.38),
        "Washington Mystics":      (38.90, -77.02),
        # NFL
        "Atlanta Falcons":         (33.76, -84.40),
        "Buffalo Bills":           (42.77, -78.79),
        "Chicago Bears":           (41.88, -87.67),
        "Cincinnati Bengals":      (39.09, -84.52),
        "Cleveland Browns":        (41.50, -81.70),
        "Dallas Cowboys":          (32.75, -97.09),
        "Denver Broncos":          (39.74, -105.02),
        "Detroit Lions":           (42.34, -83.05),
        "Green Bay Packers":       (44.50, -88.06),
        "Tennessee Titans":        (36.17, -86.77),
        "Indianapolis Colts":      (39.76, -86.16),
        "Kansas City Chiefs":      (39.05, -94.48),
        "Las Vegas Raiders":       (36.09, -115.18),
        "Los Angeles Rams":        (33.95, -118.34),
        "Miami Dolphins":          (25.96, -80.24),
        "Minnesota Vikings":       (44.97, -93.26),
        "New England Patriots":    (42.09, -71.26),
        "New Orleans Saints":      (29.95, -90.08),
        "New York Giants":         (40.81, -74.07),
        "New York Jets":           (40.81, -74.07),
        "Philadelphia Eagles":     (39.90, -75.17),
        "Arizona Cardinals":       (33.53, -112.26),
        "Pittsburgh Steelers":     (40.45, -80.02),
        "Los Angeles Chargers":    (33.95, -118.34),
        "San Francisco 49ers":     (37.40, -121.97),
        "Seattle Seahawks":        (47.60, -122.33),
        "Tampa Bay Buccaneers":    (27.98, -82.50),
        "Washington Commanders":   (38.91, -76.86),
        "Carolina Panthers":       (35.23, -80.85),
        "Jacksonville Jaguars":    (30.32, -81.64),
        "Baltimore Ravens":        (39.28, -76.62),
        "Houston Texans":          (29.68, -95.41),
        # NCAAF
        "Alabama":                 (33.21, -87.55),
        "Georgia":                 (33.95, -83.37),
        "Ohio State":              (40.00, -83.02),
        "Michigan":                (42.27, -83.75),
        "Texas":                   (30.28, -97.73),
        "Oklahoma":                (35.21, -97.44),
        "LSU":                     (30.41, -91.18),
        "Notre Dame":              (41.70, -86.23),
        "Penn State":              (40.79, -77.86),
        "Oregon":                  (44.05, -123.07),
        "Clemson":                 (34.68, -82.84),
        "Florida":                 (29.65, -82.35),
        "Tennessee":               (35.95, -83.93),
        "USC":                     (34.02, -118.29),
        "UCLA":                    (34.16, -118.17),
        "Colorado":                (40.01, -105.27),
        "Utah":                    (40.76, -111.85),
        "BYU":                     (40.25, -111.65),
        "Air Force":               (38.99, -104.86),
        "Wyoming":                 (41.31, -105.59),
        "New Mexico":              (35.08, -106.65),
        "Boise State":             (43.60, -116.20),
        "Nevada":                  (39.55, -119.82),
        "UNLV":                    (36.11, -115.14),
        "Arizona":                 (32.23, -110.95),
        "Arizona State":           (33.43, -111.93),
        "Washington":              (47.65, -122.30),
        "Miami":                   (25.91, -80.22),
        "Florida State":           (30.44, -84.30),
        "NC State":                (35.77, -78.67),
        "Wisconsin":               (43.07, -89.41),
        "Iowa":                    (41.66, -91.55),
        "Minnesota":               (44.97, -93.23),
        "Nebraska":                (40.82, -96.71),
        "Kansas State":            (39.20, -96.60),
        "TCU":                     (32.71, -97.37),
        "Baylor":                  (31.56, -97.12),
        # NCAAB
        "Duke Blue Devils":        (36.00, -78.94),
        "North Carolina Tar Heels": (35.90, -79.04),
        "Kentucky Wildcats":       (38.03, -84.49),
        "Kansas Jayhawks":         (38.95, -95.26),
        "Gonzaga Bulldogs":        (47.66, -117.40),
        "Villanova Wildcats":      (40.03, -75.34),
        "Michigan State Spartans": (42.73, -84.48),
        "Arizona Wildcats":        (32.23, -110.95),
        "UCLA Bruins":             (34.16, -118.17),
        "Indiana Hoosiers":        (39.17, -86.52),
        "Connecticut Huskies":     (41.81, -72.25),
        "Louisville Cardinals":    (38.21, -85.76),
        "Syracuse Orange":         (43.03, -76.13),
        "Texas Longhorns":         (30.28, -97.73),
        "Memphis Tigers":          (35.12, -89.94),
        "Houston Cougars":         (29.72, -95.34),
        "Iowa State Cyclones":     (42.02, -93.65),
        "Saint Louis Billikens":   (38.64, -90.23),
        "Colorado Buffaloes":      (40.01, -105.27),
        "Utah Utes":               (40.76, -111.85),
        "BYU Cougars":             (40.25, -111.65),
        "Air Force Falcons":       (38.99, -104.86),
        "Wyoming Cowboys":         (41.31, -105.59),
        "New Mexico Lobos":        (35.08, -106.65),
        "Boise State Broncos":     (43.60, -116.20),
        "Nevada Wolf Pack":        (39.55, -119.82),
        "UNLV Runnin Rebels":      (36.11, -115.14),
    }

    def haversine(lat1, lon1, lat2, lon2):
        import math
        R    = 3958.8
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a    = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
        return round(2 * R * math.asin(math.sqrt(a)), 0)

    def get_time_zones(home_team, away_team):
        home_coords = CITY_COORDS.get(home_team)
        away_coords = CITY_COORDS.get(away_team)
        if not home_coords or not away_coords:
            return 0
        lon_diff = abs(home_coords[1] - away_coords[1])
        return int(lon_diff / 15)

    for game in games:
        home_team   = game.get("home_team", "")
        away_team   = game.get("away_team", "")
        home_coords = CITY_COORDS.get(home_team)
        away_coords = CITY_COORDS.get(away_team)
        altitude_ft = ALTITUDE_MAP.get(home_team, 0)
        time_zones  = get_time_zones(home_team, away_team)

        miles = 0
        if home_coords and away_coords:
            miles = haversine(
                away_coords[0], away_coords[1],
                home_coords[0], home_coords[1]
            )

        altitude_adj = 0.0
        if altitude_ft > 2000:
            altitude_adj = -((altitude_ft - 2000) / 1000) * 0.5

        travel_adj = -(miles / 1000) * 0.3
        tz_adj     = max(-2.0, -(time_zones * 0.5))
        total_adj  = round(altitude_adj + travel_adj + tz_adj, 2)

        try:
            c.execute("""
                INSERT OR REPLACE INTO situational_factors
                (date, sport, home_team, away_team,
                 away_miles_traveled, away_time_zones,
                 home_altitude_ft, altitude_adj,
                 travel_adj, total_adj)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (today, sport, home_team, away_team,
                  miles, time_zones, altitude_ft,
                  altitude_adj, travel_adj, total_adj))
            saved += 1

            if altitude_ft > 2000 or miles > 1500:
                print(f"  TRAVEL: {away_team} @ {home_team} | "
                      f"Miles: {miles} | TZ: {time_zones} | "
                      f"Alt: {altitude_ft}ft | Adj: {total_adj}")

        except Exception as e:
            print(f"Situational log error: {e}")

    conn.commit()
    conn.close()
    print(f"Situational factors logged: {saved} games ({sport})")


def log_prediction(bet: dict, sport: str):
    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    game  = bet.get("game", "")
    parts = game.split(" @ ")

    try:
        c.execute("""
            INSERT OR REPLACE INTO predictions
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


def log_result(sport: str, game: str, date: str,
               home_score: int, away_score: int):
    conn  = get_conn()
    c     = conn.cursor()
    parts = game.split(" @ ")
    home  = parts[1] if len(parts) == 2 else ""
    away  = parts[0] if len(parts) == 2 else ""

    actual_winner = home if home_score > away_score else away

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

        status = "CORRECT" if correct == 1 else "WRONG" if correct == 0 else "NO PICK"
        print(f"Result logged: {game} - {actual_winner} wins {status}")
    except Exception as e:
        print(f"Result log error: {e}")
    finally:
        conn.close()


def model_report(sport: str = None):
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

    print("\nMODEL PERFORMANCE REPORT")
    print("-" * 45)
    for row in rows:
        print(f"{row['sport'].upper():<8} "
              f"Picks: {row['picks']:<5} "
              f"Wins: {row['wins']:<5} "
              f"Win Rate: {row['win_rate']}% "
              f"Avg Edge: {row['avg_edge']}%")
    print("-" * 45)
    conn.close()


if __name__ == "__main__":
    init_db()
    model_report()