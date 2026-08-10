"""
database.py - Culture & Pulse Sports Analytics

Central database connection and schema management.

Supports:
- Supabase Postgres (production, as of the 2026-07 migration)
- Turso libSQL (rollback fallback only — set SUPABASE_DB_URL to use
  Postgres; unset it and TURSO_DATABASE_URL/TURSO_AUTH_TOKEN take over
  again, unchanged from before the migration)
- SQLite fallback (local development)

SETUP: pip install psycopg2-binary (in addition to existing deps)
Set env var: SUPABASE_DB_URL (a full postgres:// connection string
from your Supabase project's connection settings)

MIGRATION NOTE (2026-07): Schema is now defined once, in
schema_postgres.sql, and applied directly in Supabase. This file no
longer creates tables itself — init_db() and _ensure_extended_tables()
(which each had their own, sometimes conflicting, inline CREATE TABLE
statements) have been removed for that reason. See init_db()'s
docstring below for why that old code was actually dangerous to keep,
not just outdated.

PREDICTION ENGINE v2 (2026-07-20): predictions table now supports
multiple betting markets per game (moneyline, spread, total) instead
of one row per game. See log_prediction()'s docstring below for the
schema change and how to call it for each market.
"""

import sqlite3
import os
import tempfile
from datetime import datetime


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
SUPABASE_DB_URL = (os.environ.get("SUPABASE_DB_URL") or "").strip()
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
    source instead of patching each file individually. Same wrapper is
    now reused for the Postgres/psycopg2 connection for the same
    reason."""
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
    """Wraps a driver cursor so fetchone()/fetchall() return _Row
    objects instead of plain tuples. Everything else (rowcount,
    lastrowid, description, close, ...) passes straight through to the
    real cursor via __getattr__.

    translate_placeholders: when True (Postgres/psycopg2 only), SQLite-
    style "?" placeholders in the query text are rewritten to "%s"
    before being sent to the driver. Left False for SQLite/Turso, which
    use "?" natively — this keeps every existing query string in the
    codebase unchanged; only the wrapper translates."""

    def __init__(self, real_cursor, translate_placeholders=False):
        self._cursor = real_cursor
        self._translate = translate_placeholders

    def _translate_sql(self, sql):
        if self._translate and isinstance(sql, str):
            return sql.replace("?", "%s")
        return sql

    def execute(self, *args, **kwargs):
        if args:
            args = (self._translate_sql(args[0]),) + tuple(args[1:])
        self._cursor.execute(*args, **kwargs)
        return self

    def executemany(self, *args, **kwargs):
        if args:
            args = (self._translate_sql(args[0]),) + tuple(args[1:])
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
    """Wraps a driver connection so both conn.cursor() and the direct
    conn.execute() shortcut (used in Turso's own docs, and by
    dashboard.py's get_recent_values_batch()) return dict-row-capable
    cursors. commit/close/rollback/etc. pass straight through to the
    real connection via __getattr__.

    conn.execute() is implemented via self.cursor().execute() rather
    than delegating to the real connection's own .execute() — psycopg2
    Connection objects don't have a .execute() shortcut the way
    sqlite3/libsql connections do, so delegating directly would break
    the moment this wrapped a Postgres connection. Building the cursor
    ourselves works the same way regardless of which driver is
    underneath."""

    def __init__(self, real_conn, translate_placeholders=False):
        self._conn = real_conn
        self._translate = translate_placeholders

    def cursor(self):
        return _DictCursorWrapper(self._conn.cursor(), self._translate)

    def execute(self, *args, **kwargs):
        cur = self.cursor()
        cur.execute(*args, **kwargs)
        return cur

    def __getattr__(self, name):
        return getattr(self._conn, name)


def log_odds(sport: str, games: list, source: str = "espn"):
    """Recovered from pre-regression database.py (commit b13a88a) —
    render_job.py imports this directly."""
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
                INSERT INTO odds_history
                (date, sport, home_team, away_team, home_ml, away_ml,
                 home_implied, away_implied, source, opening_home_ml, opening_away_ml)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date, sport, home_team, away_team) DO NOTHING
            """, (today, sport, home_team, away_team, home_ml, away_ml,
                  home_implied, away_implied, source, home_ml, away_ml))
            saved += 1
        except Exception as e:
            conn.rollback()
            print(f"Odds log error: {e}")

    conn.commit()
    conn.close()
    print(f"Logged {saved} games to odds_history ({sport})")


def update_closing_odds(sport: str, games: list):
    """Recovered from pre-regression database.py — used by render_job.py's noon retry."""
    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")

    try:
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
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f"Updated closing lines for {sport}")


def log_line_movement(sport: str, games: list):
    """Recovered from pre-regression database.py — render_job.py's noon retry.

    Now also RETURNS the list of sharp-signal hits it detects (game,
    sharp text), instead of only printing them — render_job.py uses
    this to build a real Telegram steam alert. Storage/print behavior
    unchanged, this is additive."""
    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    saved = 0
    sharp_hits = []

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
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
                INSERT INTO line_movement
                (date, sport, home_team, away_team,
                 opening_home_ml, opening_away_ml,
                 closing_home_ml, closing_away_ml,
                 movement_home, movement_away, sharp_signal, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date, sport, home_team, away_team) DO UPDATE SET
                    opening_home_ml = EXCLUDED.opening_home_ml,
                    opening_away_ml = EXCLUDED.opening_away_ml,
                    closing_home_ml = EXCLUDED.closing_home_ml,
                    closing_away_ml = EXCLUDED.closing_away_ml,
                    movement_home   = EXCLUDED.movement_home,
                    movement_away   = EXCLUDED.movement_away,
                    sharp_signal    = EXCLUDED.sharp_signal,
                    captured_at     = EXCLUDED.captured_at
            """, (today, sport, home_team, away_team,
                  opening_home, opening_away,
                  home_ml, away_ml,
                  movement_home, movement_away, sharp, now_str))
            saved += 1

            if sharp:
                print(f"  SHARP: {sharp} - {away_team} @ {home_team}")
                sharp_hits.append({
                    "sport": sport,
                    "game": f"{away_team} @ {home_team}",
                    "detail": sharp,
                })

        except Exception as e:
            conn.rollback()
            print(f"Line movement log error: {e}")

    conn.commit()
    conn.close()
    print(f"Line movement logged: {saved} games ({sport})")
    return sharp_hits


def log_injuries(sport: str):
    """Recovered from pre-regression database.py — render_job.py imports this directly."""
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
                    INSERT INTO injuries_log
                    (date, sport, team_name, player_name, status)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT (date, sport, team_name, player_name) DO NOTHING
                """, (today, sport, team_name, player_name, status))
                saved += 1
            except Exception as e:
                conn.rollback()
                print(f"Injury log error: {e}")

    conn.commit()
    conn.close()
    print(f"Logged {saved} injury records ({sport})")


def log_bankroll(date: str, sport: str, game: str, bet: str,
                 odds: int, stake: float, result: str,
                 profit_loss: float, bankroll_after: float,
                 edge: float = 0.0, notes: str = ""):
    """Recovered from pre-regression database.py."""
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
        conn.rollback()
        print(f"Bankroll log error: {e}")
    finally:
        conn.close()


def get_bankroll_summary():
    """Recovered from pre-regression database.py."""
    conn = get_conn()
    c    = conn.cursor()

    try:
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
    finally:
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
        print(f"  {'-'*35}")
        for s in by_sport:
            pl_val = s['pl'] or 0
            pl_str = f"+${pl_val}" if pl_val >= 0 else f"-${abs(pl_val)}"
            print(f"  {s['sport'].upper():<10} {s['bets']} bets | {s['win_rate']}% | {pl_str}")

    print(f"{'='*50}\n")


# Maps each sport to the game log table that has one row per team per
# game played — used to find a team's most recent game date so rest
# days / back-to-back can be computed. Same table set dashboard.py's
# GAME_LOG_TABLES already uses for sparklines.
SITUATIONAL_GAME_LOG_TABLES = {
    "wnba": "wnba_game_log",
    "nba":  "nba_game_log",
    "mlb":  "mlb_game_log",
    "nfl":  "nfl_game_log",
}


def _get_rest_days(conn, team_name: str, sport: str, game_date: str) -> int:
    """Days since this team's most recent PRIOR game (strictly before
    game_date). Returns 1 (treated as a back-to-back trigger) if no
    prior game is on record — safer default than guessing a large
    rest gap for a team with no logged history yet."""
    table = SITUATIONAL_GAME_LOG_TABLES.get(sport)
    if not table:
        return 1
    try:
        c = conn.cursor()
        c.execute(f"""
            SELECT MAX(date) as last_date FROM {table}
            WHERE team_name = ? AND date < ?
        """, (team_name, game_date))
        row = c.fetchone()
        last_date = row["last_date"] if row else None
        if not last_date:
            return 1
        d1 = datetime.strptime(game_date.replace("-", ""), "%Y%m%d") if "-" not in game_date[:4] or len(game_date) == 8 else datetime.strptime(game_date, "%Y-%m-%d")
        d0_str = last_date if "-" in str(last_date) else f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:]}"
        d0 = datetime.strptime(d0_str, "%Y-%m-%d")
        return max((d1 - d0).days, 0)
    except Exception:
        return 1


def get_line_movement_adj(home_team: str, away_team: str, sport: str, date: str = None):
    """
    Reads today's already-computed line_movement row for this matchup
    and converts it into a small point adjustment per team, same
    pattern as get_situational_row(). render_job.py's noon retry runs
    update_closing_odds()/log_line_movement() BEFORE this would ever
    be called by an evening rerun — but for the common case (predict()
    called earlier in the day, before the noon retry), this table
    often won't have a row yet. Returns (0.0, 0.0) in that case, same
    as every other factor's "no data yet" fallback — never a guess.

    Deliberately a SMALL nudge, not a primary signal (per the agreed
    Tier 3 guidance). Scaled per sport — same lesson as
    SPORT_INJURY_SCALE in intel_feed.py: a flat point cap only makes
    sense for one sport's scoring range. WNBA/NBA run ~85-100 pts,
    NFL/CFB ~22-29 pts, MLB ~4.5 runs — a cap sized for basketball
    would be a third of an MLB team's entire projected score.
    """
    LINE_MOVEMENT_SCALE = {
        # (points per 10-pt odds move, max cap)
        "WNBA": (0.3, 1.5),
        "NBA":  (0.3, 1.5),
        "NFL":  (0.12, 0.6),
        "CFB":  (0.12, 0.6),
        "MLB":  (0.03, 0.15),
    }
    per_10pt, cap = LINE_MOVEMENT_SCALE.get(sport.upper(), (0.3, 1.5))

    date = date or datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT movement_home, movement_away
            FROM line_movement
            WHERE date = ? AND sport = ? AND home_team = ? AND away_team = ?
        """, (date, sport, home_team, away_team))
        row = c.fetchone()
        if not row or row["movement_home"] is None or row["movement_away"] is None:
            return 0.0, 0.0

        def _to_pts(movement):
            # Odds getting MORE negative (shorter) = market backing
            # that team harder = positive point adjustment for them.
            pts = -movement / 10 * per_10pt
            return round(max(min(pts, cap), -cap), 3)

        return _to_pts(row["movement_home"]), _to_pts(row["movement_away"])
    except Exception:
        return 0.0, 0.0
    finally:
        conn.close()


def get_situational_row(home_team: str, away_team: str, sport: str, date: str = None):
    """Reads today's already-computed situational_factors row for this
    matchup. Shared across every sport predictor (wnba, mlb, cfb, nfl)
    instead of each one carrying its own copy — render_job.py's daily
    job runs log_situational_factors() BEFORE predictions are
    generated, so this row should already exist for any game being
    predicted same-day. Returns None if no row exists yet (callers
    fall back to their own live rest-days lookup, not a guess)."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("""
            SELECT home_rest_days, away_rest_days, total_adj
            FROM situational_factors
            WHERE date = ? AND sport = ? AND home_team = ? AND away_team = ?
        """, (date, sport, home_team, away_team))
        return c.fetchone()
    except Exception:
        return None
    finally:
        conn.close()


def log_situational_factors(sport: str, games: list):
    """Recovered from pre-regression database.py — render_job.py imports this directly.
    Full ALTITUDE_MAP/CITY_COORDS dicts kept as-is from the original.

    2026-07: added real back_to_back/rest_days calculation — the
    situational_factors table always had these columns, but this
    function never computed or saved them, so they sat empty since the
    table was created."""
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

        home_rest_days = _get_rest_days(conn, home_team, sport, today)
        away_rest_days = _get_rest_days(conn, away_team, sport, today)
        home_back_to_back = 1 if home_rest_days <= 1 else 0
        away_back_to_back = 1 if away_rest_days <= 1 else 0

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
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("""
                INSERT INTO situational_factors
                (date, sport, home_team, away_team,
                 away_miles_traveled, away_time_zones,
                 home_altitude_ft, altitude_adj,
                 travel_adj, total_adj, captured_at,
                 home_rest_days, away_rest_days,
                 home_back_to_back, away_back_to_back)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (date, sport, home_team, away_team) DO UPDATE SET
                    away_miles_traveled = EXCLUDED.away_miles_traveled,
                    away_time_zones     = EXCLUDED.away_time_zones,
                    home_altitude_ft    = EXCLUDED.home_altitude_ft,
                    altitude_adj        = EXCLUDED.altitude_adj,
                    travel_adj          = EXCLUDED.travel_adj,
                    total_adj           = EXCLUDED.total_adj,
                    captured_at         = EXCLUDED.captured_at,
                    home_rest_days      = EXCLUDED.home_rest_days,
                    away_rest_days      = EXCLUDED.away_rest_days,
                    home_back_to_back   = EXCLUDED.home_back_to_back,
                    away_back_to_back   = EXCLUDED.away_back_to_back
            """, (today, sport, home_team, away_team,
                  miles, time_zones, altitude_ft,
                  altitude_adj, travel_adj, total_adj, now_str,
                  home_rest_days, away_rest_days,
                  home_back_to_back, away_back_to_back))
            saved += 1

            if altitude_ft > 2000 or miles > 1500:
                print(f"  TRAVEL: {away_team} @ {home_team} | "
                      f"Miles: {miles} | TZ: {time_zones} | "
                      f"Alt: {altitude_ft}ft | Adj: {total_adj}")

        except Exception as e:
            conn.rollback()
            print(f"Situational log error: {e}")

    conn.commit()
    conn.close()
    print(f"Situational factors logged: {saved} games ({sport})")


def model_report(sport: str = None):
    """Recovered from pre-regression database.py."""
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
    try:
        c.execute(query, params)
        rows = c.fetchall()
    finally:
        conn.close()

    print("\nMODEL PERFORMANCE REPORT")
    print("-" * 45)
    for row in rows:
        print(f"{row['sport'].upper():<8} "
              f"Picks: {row['picks']:<5} "
              f"Wins: {row['wins']:<5} "
              f"Win Rate: {row['win_rate']}% "
              f"Avg Edge: {row['avg_edge']}%")
    print("-" * 45)


def log_prediction(bet: dict, sport: str, market: str = "moneyline"):
    """Recovered from pre-regression database.py (commit b13a88a) —
    render_job.py imports this directly. Column names (bet, model_prob,
    home_record, predicted_winner, etc.) confirmed matching PRODUCTION's
    actual live schema (see schema_postgres.sql).

    2026-07-13: added an explicit app-level dedupe check before the
    insert (kept unchanged in this migration). The DB's
    UNIQUE(date, sport, game) constraint kept reverting under Turso for
    reasons never fully traced; this check makes the app enforce
    one-row-per-game-per-day regardless of what the DB constraint is
    doing. The ON CONFLICT clause added below is defense-in-depth on
    top of that guard, not a replacement for it — kept both since the
    guard already proved itself against the exact failure mode that
    caused the July 13 incident.

    2026-07-20 (Prediction Engine v2): predictions can now hold up to
    3 rows per game — one per market (moneyline / spread / total) —
    instead of one row overwriting the last. The dedupe/conflict key
    is now (date, sport, game, market), matching the new UNIQUE
    constraint on the predictions table. Call this once per market
    your predictor generates for a game:

        log_prediction(ml_bet, sport, market="moneyline")
        log_prediction(spread_bet, sport, market="spread")
        log_prediction(total_bet, sport, market="total")

    Existing callers that don't pass market at all keep working
    unchanged (defaults to "moneyline", same behavior as before this
    change).

    bet dict now also accepts these optional keys, used by the new
    columns: pick, line, projected_home, projected_away,
    projected_margin, projected_total, confidence. All default to
    None/"" if not provided, so old-style bet dicts (moneyline-only,
    pre-v2 callers) still insert cleanly."""
    conn  = get_conn()
    c     = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    game  = bet.get("game", "")
    parts = game.split(" @ ")

    try:
        # Dedupe guard — delete any existing row for this exact
        # date/sport/game/market before inserting, so a flipped pick on
        # a rerun replaces the old one instead of creating a duplicate.
        # market is now part of the key so ML/Spread/Total rows for the
        # same game no longer overwrite each other.
        c.execute(
            "SELECT id FROM predictions WHERE date=? AND sport=? AND game=? AND market=?",
            (today, sport, game, market)
        )
        existing = c.fetchone()
        if existing:
            c.execute("DELETE FROM predictions WHERE id=?", (existing["id"],))

        c.execute("""
            INSERT INTO predictions
            (date, sport, game, home_team, away_team, bet, odds,
             model_prob, implied_prob, edge, home_record, away_record,
             home_rest, away_rest, home_injuries, away_injuries, predicted_winner,
             market, pick, line, projected_home, projected_away,
             projected_margin, projected_total, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (date, sport, game, market) DO UPDATE SET
                home_team        = EXCLUDED.home_team,
                away_team        = EXCLUDED.away_team,
                bet              = EXCLUDED.bet,
                odds             = EXCLUDED.odds,
                model_prob       = EXCLUDED.model_prob,
                implied_prob     = EXCLUDED.implied_prob,
                edge             = EXCLUDED.edge,
                home_record      = EXCLUDED.home_record,
                away_record      = EXCLUDED.away_record,
                home_rest        = EXCLUDED.home_rest,
                away_rest        = EXCLUDED.away_rest,
                home_injuries    = EXCLUDED.home_injuries,
                away_injuries    = EXCLUDED.away_injuries,
                predicted_winner = EXCLUDED.predicted_winner,
                pick             = EXCLUDED.pick,
                line             = EXCLUDED.line,
                projected_home   = EXCLUDED.projected_home,
                projected_away   = EXCLUDED.projected_away,
                projected_margin = EXCLUDED.projected_margin,
                projected_total  = EXCLUDED.projected_total,
                confidence       = EXCLUDED.confidence
        """, (
            today, sport, game,
            parts[1] if len(parts) == 2 else "",
            parts[0] if len(parts) == 2 else "",
            bet.get("bet", ""),
            bet.get("odds"),
            bet.get("model_prob", 0),
            bet.get("implied_prob", 0) if bet.get("implied_prob") is not None else None,
            round(bet["edge"] * 100, 2) if bet.get("edge") is not None else None,
            bet.get("home_record", ""),
            bet.get("away_record", ""),
            bet.get("home_rest"),
            bet.get("away_rest"),
            bet.get("home_injuries", ""),
            bet.get("away_injuries", ""),
            bet.get("bet", "").replace(" ML", ""),
            market,
            bet.get("pick", ""),
            bet.get("line"),
            bet.get("projected_home"),
            bet.get("projected_away"),
            bet.get("projected_margin"),
            bet.get("projected_total"),
            bet.get("confidence", ""),
        ))
        conn.commit()
        print(f"Logged prediction: {game} [{market}]")
    except Exception as e:
        conn.rollback()
        print(f"Prediction log error: {e}")
    finally:
        conn.close()


def save_prediction_factors(sport: str, game_id: str, home_team: str,
                             away_team: str, home_score_final: float,
                             away_score_final: float, home_factors: dict,
                             away_factors: dict, prediction_id: int = None):
    """
    Explainability layer — logs the individual point adjustments that
    produced each team's final projected score, into the standalone
    prediction_factors table (see create_prediction_factors.sql).
    Deliberately NOT joined into predictions/log_prediction() itself;
    additive-only table given the 7/13 predictions incident, so a bug
    here can never touch the actual prediction ledger.

    game_id should be date-scoped (e.g. "2026-07-15_LAL_MIN") so the
    same matchup happening twice in a season doesn't collide against
    the UNIQUE(sport, game_id) constraint.

    factors dicts are point adjustments only (v1 — no base/final
    probability split, no second Monte Carlo run), e.g.:
        {"home_advantage": 4.2, "rest": 1.8, "injury": -6.0,
         "situational": -0.9, "line_movement": 0.6}

    Safe to call even if this fails — wrapped so a logging error never
    blocks the actual prediction from being made or saved.
    """
    import json
    conn = get_conn()
    c    = conn.cursor()
    try:
        c.execute("""
            INSERT INTO prediction_factors
            (prediction_id, game_id, sport, home_team, away_team,
             home_score_final, away_score_final, home_factors, away_factors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (sport, game_id) DO UPDATE SET
                prediction_id     = EXCLUDED.prediction_id,
                home_team         = EXCLUDED.home_team,
                away_team         = EXCLUDED.away_team,
                home_score_final  = EXCLUDED.home_score_final,
                away_score_final  = EXCLUDED.away_score_final,
                home_factors      = EXCLUDED.home_factors,
                away_factors      = EXCLUDED.away_factors,
                created_at        = NOW()
        """, (
            prediction_id, game_id, sport, home_team, away_team,
            home_score_final, away_score_final,
            json.dumps(home_factors), json.dumps(away_factors),
        ))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"  [factors] save error (non-fatal, prediction unaffected): {e}")
    finally:
        conn.close()


def _grade_prediction(pred, home: str, away: str, home_score: int, away_score: int) -> tuple:
    """Grades ONE predictions row against the final score, according to
    its own market. Returns (correct, push):
        correct: 1 (won) / 0 (lost) / None (push or ungradeable)
        push:    True only for a genuine push (line landed exactly on
                 the number) — distinct from "pending", since the game
                 IS over. results.correct alone can't carry this
                 distinction (NULL already means "pending" everywhere
                 else in the app), hence the separate push column.

    market == "moneyline": win/loss only, no push possible (a tied
        final score doesn't happen in these sports).
    market == "spread": pick's actual margin (their score - opponent's
        score) plus their line. > 0 covers, < 0 doesn't, == 0 pushes.
    market == "total": actual combined score vs the posted total line.
        > line hits Over, < line hits Under, == line pushes.

    Any row with a market this function doesn't recognize, or missing
    the pick/line data it needs, grades as (None, False) — same as
    "no data yet", never a guess.
    """
    market = (pred["market"] or "moneyline").lower()
    pick = pred["pick"]
    line = pred["line"]
    actual_winner = home if home_score > away_score else away

    if market == "moneyline":
        predicted_winner = pred["predicted_winner"]
        if not predicted_winner:
            return None, False
        return (1 if predicted_winner == actual_winner else 0), False

    if market == "spread":
        if not pick or line is None:
            return None, False
        if pick == home:
            pick_margin = home_score - away_score
        elif pick == away:
            pick_margin = away_score - home_score
        else:
            return None, False
        cover_value = pick_margin + line
        if cover_value > 0:
            return 1, False
        if cover_value < 0:
            return 0, False
        return None, True  # push

    if market == "total":
        if not pick or line is None:
            return None, False
        total_actual = home_score + away_score
        if pick.lower() == "over":
            if total_actual > line:
                return 1, False
            if total_actual < line:
                return 0, False
            return None, True  # push
        if pick.lower() == "under":
            if total_actual < line:
                return 1, False
            if total_actual > line:
                return 0, False
            return None, True  # push
        return None, False

    return None, False


def log_result(sport: str, game: str, date: str,
               home_score: int, away_score: int):
    """Recovered from pre-regression database.py — not directly called
    by auto_results.py (which has its own insert_result() with the same
    logic inline), but kept for any other caller and for parity with
    the original file.

    results.prediction_id has a real UNIQUE constraint (see
    schema_postgres.sql). Rows where prediction_id is NULL (no matching
    prediction found) never conflict under that constraint in Postgres
    — same as SQLite, which also treats NULLs as distinct for UNIQUE
    purposes — so this preserves the original "always insert if no
    prediction_id" behavior without extra handling.

    PREDICTION ENGINE v2 (2026-07-20): now grades EVERY predictions row
    for this game/date — up to 3 (moneyline/spread/total) — instead of
    just one. Each market is graded by its own rule via
    _grade_prediction() and gets its OWN results row (one per
    prediction_id, same UNIQUE constraint as before). A push (spread or
    total landing exactly on the line) is stored as correct=NULL,
    push=TRUE — distinct from a genuinely pending/ungraded pick
    (correct=NULL, push=FALSE), since the game IS over for a push, it
    just didn't resolve either way. Requires the `push` column added to
    `results` (ALTER TABLE results ADD COLUMN push BOOLEAN DEFAULT
    FALSE) — run that once before this version goes live.

    If no predictions rows exist at all for this game/date, still
    inserts one unmatched results row (prediction_id=NULL, correct=NULL,
    push=FALSE) — same fallback behavior the old single-row version
    had, so the game's final score is on record even with no pick to
    grade."""
    conn  = get_conn()
    c     = conn.cursor()
    parts = game.split(" @ ")
    home  = parts[1] if len(parts) == 2 else ""
    away  = parts[0] if len(parts) == 2 else ""

    actual_winner = home if home_score > away_score else away

    c.execute("""
        SELECT id, market, pick, line, predicted_winner, edge, odds
        FROM predictions
        WHERE date = ? AND sport = ? AND game = ?
    """, (date, sport, game))
    preds = c.fetchall()

    rows_to_grade = preds if preds else [None]
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    graded_summary = []

    try:
        for pred in rows_to_grade:
            if pred is None:
                pred_id, edge_at_pick, odds_at_pick = None, None, None
                correct, push = None, False
                market_label = "no pick"
            else:
                pred_id      = pred["id"]
                edge_at_pick = pred["edge"]
                odds_at_pick = pred["odds"]
                correct, push = _grade_prediction(pred, home, away, home_score, away_score)
                market_label = pred["market"] or "moneyline"

            c.execute("""
                INSERT INTO results
                (date, sport, game, home_team, away_team,
                 home_score, away_score, actual_winner,
                 prediction_id, correct, push, edge_at_pick, odds_at_pick, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (prediction_id) DO UPDATE SET
                    date          = EXCLUDED.date,
                    sport         = EXCLUDED.sport,
                    game          = EXCLUDED.game,
                    home_team     = EXCLUDED.home_team,
                    away_team     = EXCLUDED.away_team,
                    home_score    = EXCLUDED.home_score,
                    away_score    = EXCLUDED.away_score,
                    actual_winner = EXCLUDED.actual_winner,
                    correct       = EXCLUDED.correct,
                    push          = EXCLUDED.push,
                    edge_at_pick  = EXCLUDED.edge_at_pick,
                    odds_at_pick  = EXCLUDED.odds_at_pick,
                    updated_at    = EXCLUDED.updated_at
            """, (date, sport, game, home, away,
                  home_score, away_score, actual_winner,
                  pred_id, correct, push, edge_at_pick, odds_at_pick, now_str))

            status = "PUSH" if push else "CORRECT" if correct == 1 else "WRONG" if correct == 0 else "NO PICK"
            graded_summary.append(f"{market_label}={status}")

        conn.commit()
        print(f"Result logged: {game} - {actual_winner} wins | {', '.join(graded_summary)}")
    except Exception as e:
        conn.rollback()
        print(f"Result log error: {e}")
    finally:
        conn.close()


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
    and wnba/mlb/nba_defense_ratings.py. Building the dict from
    cursor.description explicitly works the same way regardless of what
    row type any driver (SQLite, Turso, or now Postgres) returns."""
    if rows is None:
        return []
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in rows]

def get_conn():

    if SUPABASE_DB_URL:

        import psycopg2
        import time

        conn = None
        last_error = None
        for attempt in range(1, 4):
            try:
                conn = psycopg2.connect(SUPABASE_DB_URL, connect_timeout=10)
                break
            except psycopg2.OperationalError as e:
                last_error = e
                print(f"[get_conn] Attempt {attempt}/3 failed: {e}")
                if attempt < 3:
                    time.sleep(5 * attempt)  # 5s, then 10s
        if conn is None:
            raise last_error

        return _DictConnWrapper(conn, translate_placeholders=True)

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
    """MIGRATION NOTE (2026-07): this used to CREATE TABLE the app's
    core tables (predictions, results, odds_history, team_stats,
    player_props, bankroll) with CREATE TABLE IF NOT EXISTS. That
    schema had drifted badly from what production actually runs —
    e.g. its version of `predictions` used columns like `prediction`,
    `model_probability`, and `confidence`, none of which match the
    real live schema (`bet`, `model_prob`, `home_record`, etc. — see
    log_prediction() above and schema_postgres.sql). It only ever
    looked safe because IF NOT EXISTS never touches a table that
    already exists — if this had ever run against an empty database,
    it would have silently created the wrong table shape.

    Schema is now defined once, in schema_postgres.sql, and applied
    directly against Supabase. This function is kept as a no-op (not
    deleted outright) in case something still imports or calls it."""
    print("init_db() is a no-op as of the 2026-07 migration — "
          "schema is managed in schema_postgres.sql, applied directly "
          "in Supabase, not created from this file.")



# --------------------------------------------------
# TEST
# --------------------------------------------------

if __name__ == "__main__":

    init_db()
