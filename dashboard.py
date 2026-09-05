"""
Culture & Pulse Picks — Tracking Dashboard
Pulls game picks + player props from Turso (cp-analytics DB).

SETUP:
1. pip install streamlit psycopg2-binary pandas
2. Set env vars: SUPABASE_DB_URL, DASHBOARD_PASSWORD
   (TURSO_DATABASE_URL / TURSO_AUTH_TOKEN kept as rollback fallback —
   see database.py)
3. Deploy on Render or any platform — no longer tied to Linux-only wheels

Schemas used:
- predictions / results: game picks, joined on prediction_id (see earlier notes).
  As of Prediction Engine v2 (2026-07-20), predictions can hold up to 3 rows
  per game — one per market (moneyline / spread / total) — keyed on
  (date, sport, game, market). load_picks() below pulls the new market,
  pick, line, projected_home, projected_away, projected_margin,
  projected_total, and confidence columns.
- player_props: date, sport, player_name, team_name, opponent, home_away, stat,
  line, over_odds, under_odds, hit_rate_overall, hit_rate_vs_opp,
  hit_rate_home_away, hit_rate_b2b, games_overall, games_vs_opp,
  games_home_away, confidence_tier, source, captured_at
- prop_results: date, sport, player_name, team_name, opponent, home_away, stat,
  line, actual_value, hit (1/0/NULL), team_won, over_odds, under_odds,
  source, scored_at — joined to player_props on (date, player_name, stat)

NOTE: libsql-experimental's cursor.description is NOT reliable for column
names in joined queries — column names are assigned manually in the exact
order of each SELECT clause instead of trusting cur.description.

NOTE: player_props loading (with the PRAGMA table_info column-existence
check) lives in load_props.py, not in this file — Tab 2 calls
load_props.load_props(). Don't redefine that logic here again; a prior
version of this file had a second function also named load_picks() that
did the props query — it silently overwrote the real load_picks() (Game
Picks) above it in Python, so Tab 1 was loading props data by mistake.

CONNECTION HANDLING: get_conn() below wraps database.get_conn() with
@st.cache_resource so Streamlit reuses ONE connection across reruns
instead of opening a new libsql connection + full Turso sync on every
call. This must run AFTER load_dotenv() and BEFORE database.py is
imported, since database.py reads TURSO_DATABASE_URL/TURSO_AUTH_TOKEN
from os.environ at import time — importing database before .env is
loaded locks in blank credentials.

SPARKLINE BATCHING: get_recent_values_batch() below fetches recent
game-log values for ALL players sharing a (sport, stat) pair in ONE
query, instead of the old get_recent_values() pattern of one query per
row (100-400+ queries per Player Props page load). That per-row pattern,
even after the connection-caching fix, was still enough rapid-fire
query volume to crash cp-picks-dashboard on Render's 512MB free tier
(exit 139 / SIGSEGV) roughly every 15 min whenever someone opened the
Player Props tab. Batching by (sport, stat) cuts hundreds of queries
down to typically under 20 per page load.
"""

from dotenv import load_dotenv
load_dotenv()

import os
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from database import get_conn as _get_conn_raw

@st.cache_resource
def get_conn():
    """Reuses one connection across reruns instead of opening a new
    libsql connection + full Turso sync on every call."""
    return _get_conn_raw()

import load_props
import ranking_engine
import performance_tracker
import edge_finder
import player_profile

st.set_page_config(page_title="Culture & Pulse Picks", layout="wide", initial_sidebar_state="collapsed")

# ---------- PASSWORD GATE ----------
# Set DASHBOARD_PASSWORD in Render's env vars. Anyone with the URL otherwise
# sees your model's edge %, picks, and full performance — lock it before
# sharing this link with anyone outside yourself.
#
# FIXED 2026-07-20: pure st.session_state["authenticated"] lives only in
# memory tied to the active WebSocket session. Mobile browsers aggressively
# kill backgrounded Streamlit tabs (locking the screen, switching apps,
# even just idling) — reconnecting after that starts a BRAND NEW session,
# wiping session_state and forcing a re-login every time. Fix: also accept
# a token in the URL query string. On successful password entry, redirect
# to a URL with ?auth=<token> appended — bookmark THAT link (or add it to
# your phone's home screen) and future visits skip the password entirely,
# since the token travels in the URL itself, not in session memory.
def check_password():
    auth_token = os.environ.get("DASHBOARD_PASSWORD", "")

    # already-valid token in the URL — no session_state needed at all
    if auth_token and st.query_params.get("auth") == auth_token:
        st.session_state["authenticated"] = True
        return True

    def password_entered():
        if st.session_state.get("pw_input") == auth_token:
            st.session_state["authenticated"] = True
            st.query_params["auth"] = auth_token
            del st.session_state["pw_input"]
        else:
            st.session_state["authenticated"] = False

    if st.session_state.get("authenticated"):
        return True

    st.markdown(
        '<div style="text-align:center;margin-top:80px;">'
        '<div style="font-family:\'Bebas Neue\',sans-serif;font-size:32px;color:#fff;letter-spacing:1px;">Culture & Pulse Picks</div>'
        '<div style="color:#8a7d55;font-size:12px;margin-bottom:20px;font-family:\'Oswald\',sans-serif;letter-spacing:1.5px;text-transform:uppercase;">Enter password to continue</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.text_input("Password", type="password", key="pw_input", on_change=password_entered, label_visibility="collapsed")
        if st.session_state.get("authenticated") is False:
            st.error("Incorrect password")
        if st.session_state.get("authenticated"):
            st.caption("📱 On mobile: bookmark this page now (or add to Home Screen) — the URL now has your login baked in, so you won't be asked again.")
    return False

# ---------- PASSWORD GATE: DISABLED 2026-07-20 per Drew's request ----------
# Not needed right now. check_password() above is left intact (unused) —
# to turn it back on later, uncomment the 4 lines below.
#
# if not os.environ.get("DASHBOARD_PASSWORD"):
#     st.warning("DASHBOARD_PASSWORD not set — dashboard is unprotected. Add it in Render's environment variables.")
# elif not check_password():
#     st.stop()

# ---------- TEAM LOGO LOOKUP ----------
# ESPN team IDs, copied from mlb_data.py / advanced_metrics.py so this file
# stays standalone (no import dependency on the main repo's modules).
MLB_TEAM_IDS = {
    "Arizona Diamondbacks": 29, "Athletics": 11, "Atlanta Braves": 15,
    "Baltimore Orioles": 1, "Boston Red Sox": 2, "Chicago Cubs": 16,
    "Chicago White Sox": 4, "Cincinnati Reds": 17, "Cleveland Guardians": 5,
    "Colorado Rockies": 27, "Detroit Tigers": 6, "Houston Astros": 18,
    "Kansas City Royals": 7, "Los Angeles Angels": 3, "Los Angeles Dodgers": 19,
    "Miami Marlins": 28, "Milwaukee Brewers": 8, "Minnesota Twins": 9,
    "New York Mets": 21, "New York Yankees": 10, "Philadelphia Phillies": 22,
    "Pittsburgh Pirates": 23, "San Diego Padres": 25, "San Francisco Giants": 26,
    "Seattle Mariners": 12, "St. Louis Cardinals": 24, "Tampa Bay Rays": 30,
    "Texas Rangers": 13, "Toronto Blue Jays": 14, "Washington Nationals": 20,
}
WNBA_TEAM_IDS = {
    "Atlanta Dream": 20, "Chicago Sky": 19, "Connecticut Sun": 18,
    "Dallas Wings": 3, "Golden State Valkyries": 129689, "Indiana Fever": 5,
    "Las Vegas Aces": 17, "Los Angeles Sparks": 6, "Minnesota Lynx": 8,
    "New York Liberty": 9, "Phoenix Mercury": 11, "Portland Fire": 132052,
    "Seattle Storm": 14, "Toronto Tempo": 131935, "Washington Mystics": 16,
}
NFL_TEAM_IDS = {
    "Atlanta Falcons": 1, "Buffalo Bills": 2, "Chicago Bears": 3,
    "Cincinnati Bengals": 4, "Cleveland Browns": 5, "Dallas Cowboys": 6,
    "Denver Broncos": 7, "Detroit Lions": 8, "Green Bay Packers": 9,
    "Tennessee Titans": 10, "Indianapolis Colts": 11, "Kansas City Chiefs": 12,
    "Las Vegas Raiders": 13, "Los Angeles Rams": 14, "Miami Dolphins": 15,
    "Minnesota Vikings": 16, "New England Patriots": 17, "New Orleans Saints": 18,
    "New York Giants": 19, "New York Jets": 20, "Philadelphia Eagles": 21,
    "Arizona Cardinals": 22, "Pittsburgh Steelers": 23, "Los Angeles Chargers": 24,
    "San Francisco 49ers": 25, "Seattle Seahawks": 26, "Tampa Bay Buccaneers": 27,
    "Washington Commanders": 28, "Carolina Panthers": 29, "Jacksonville Jaguars": 30,
    "Baltimore Ravens": 33, "Houston Texans": 34,
}
TEAM_ID_MAPS = {"mlb": MLB_TEAM_IDS, "wnba": WNBA_TEAM_IDS, "nfl": NFL_TEAM_IDS}

ESPN_LOGO_PATH = {"wnba": "wnba", "nba": "nba", "mlb": "mlb", "nfl": "nfl"}

def team_logo_url(sport: str, team_name: str) -> str:
    sport = (sport or "").lower()
    ids = TEAM_ID_MAPS.get(sport, {})
    team_id = ids.get(team_name)
    if not team_id:
        return ""
    path = ESPN_LOGO_PATH.get(sport, sport)
    return f"https://a.espncdn.com/i/teamlogos/{path}/500/{team_id}.png"

def initials_avatar(name: str) -> str:
    """Colored circle with initials — used in place of a real headshot since
    player_props doesn't store ESPN player IDs to pull real photos from."""
    parts = (name or "").split()
    initials = "".join(p[0] for p in parts[:2]).upper() or "?"
    hue = sum(ord(c) for c in name) % 360 if name else 0
    return (
        f'<div style="width:40px;height:40px;border-radius:50%;'
        f'background:hsl({hue},45%,28%);color:#fff;display:flex;'
        f'align-items:center;justify-content:center;font-weight:800;'
        f'font-size:14px;flex-shrink:0;">{initials}</div>'
    )

def grade_from_pct(pct: float) -> tuple:
    """Converts a win% into a letter grade + color. Anchored to -110
    breakeven (~52.4%) since that's the real bar for 'is this profitable',
    not just 'is this above 50%'."""
    if pct >= 65:
        return "A+", "#4CAF7D"
    if pct >= 60:
        return "A", "#4CAF7D"
    if pct >= 55:
        return "B", "#7FC79E"
    if pct >= 52.4:
        return "C", "#E3A339"
    if pct >= 48:
        return "D", "#E38A39"
    return "F", "#E1615A"

# ---------- MARKET DISPLAY HELPERS (Prediction Engine v2) ----------
MARKET_LABELS = {"moneyline": "ML", "spread": "Spread", "total": "Total"}

def market_label(market: str) -> str:
    return MARKET_LABELS.get((market or "moneyline").lower(), (market or "ML").upper())

def pick_display(row) -> str:
    """Builds a clean 'Yankees -1.5' / 'Over 8.5' / 'Yankees' string from
    the pick + line columns, falling back to the old 'bet' text field for
    rows logged before Prediction Engine v2 added pick/line."""
    pick = row.get("pick") if hasattr(row, "get") else row["pick"]
    line = row.get("line") if hasattr(row, "get") else row["line"]
    if not pick:
        return row.get("bet", "") if hasattr(row, "get") else row["bet"]
    if pd.notna(line) and line not in (None, ""):
        sign = "+" if float(line) > 0 else ""
        return f"{pick} {sign}{line}"
    return pick

# ---------- SPARKLINE PROPS TABLE (custom HTML/JS component) ----------
# Streamlit's native st.dataframe renders to canvas internally, so it can't
# show an inline recent-form sparkline per row — the thing that makes
# Outlier/Bobby's Bets props tables actually useful at a glance. This
# builds a real HTML table instead, with server-rendered SVG sparklines
# (last 10 games vs the line, colored by hit/miss) and a small vanilla-JS
# click-to-sort so we don't lose the sortability of the native table.

GAME_LOG_TABLES = {"wnba": "wnba_game_log", "mlb": "mlb_game_log", "nba": "nba_game_log", "nfl": "nfl_game_log"}

# Pitching stats live in a SEPARATE table from batting (mlb_pitcher_game_log,
# not mlb_game_log) — confirmed real and working since 2026-07-20. Any MLB
# stat in PITCHER_STATS gets routed to this table instead of the batting one.
PITCHER_GAME_LOG_TABLES = {"mlb": "mlb_pitcher_game_log"}
PITCHER_STATS = {"mlb": {"strikeouts", "hits_allowed"}}

STAT_COLS = {
    "wnba": {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
             "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")},
    "nba":  {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
             "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")},
    "mlb":  {"hits": "hits", "runs": "runs", "rbis": "rbis", "hr": "hrs",
             "strikeouts": "strikeouts", "hits_allowed": "hits_allowed"},
    "nfl":  {
        "passing_completions": "passing_completions", "passing_attempts": "passing_attempts",
        "passing_yards": "passing_yards", "passing_tds": "passing_tds", "interceptions": "interceptions",
        "rushing_attempts": "rushing_attempts", "rushing_yards": "rushing_yards", "rushing_tds": "rushing_tds",
        "receptions": "receptions", "receiving_yards": "receiving_yards", "receiving_tds": "receiving_tds",
    },
}

@st.cache_data(ttl=300)
def get_recent_values_batch(sport: str, stat: str, player_names: tuple, n: int = 10) -> dict:
    """Fetches recent game-log values for ALL players sharing a
    (sport, stat) pair in ONE query, instead of one query per player.
    Returns {player_name: [values oldest->newest]}.

    Replaces the old get_recent_values() which was called once per row
    in the Player Props table (100-400+ queries per page load) — that
    query volume, even with a cached/reused connection, was still
    crashing cp-picks-dashboard on Render's 512MB free tier roughly
    every 15 min whenever the Player Props tab was opened."""
    if stat in PITCHER_STATS.get(sport, set()):
        table = PITCHER_GAME_LOG_TABLES.get(sport)
    else:
        table = GAME_LOG_TABLES.get(sport)
    if not table or not player_names:
        return {}
    col_def = STAT_COLS.get(sport, {}).get(stat)
    if col_def is None:
        return {}
    select_expr = " + ".join(col_def) if isinstance(col_def, tuple) else col_def
    placeholders = ",".join("?" * len(player_names))
    try:
        conn = get_conn()
        cur = conn.execute(
            f"SELECT player_name, {select_expr} as val, date FROM {table} "
            f"WHERE player_name IN ({placeholders}) ORDER BY player_name, date DESC",
            player_names,
        )
        rows = cur.fetchall()
    except Exception:
        return {}

    grouped = {}
    for r in rows:
        name, val = r[0], r[1]
        if val is None:
            continue
        grouped.setdefault(name, []).append(val)

    # rows come back date DESC per player; keep only the most recent n,
    # then reverse so the sparkline reads oldest -> newest left to right
    return {name: list(reversed(vals[:n])) for name, vals in grouped.items()}


def sparkline_svg(values: list, line_value: float, direction: str = "over", width: int = 90, height: int = 28) -> str:
    """Tiny inline SVG: recent-game trend line + dashed reference line at
    the prop's betting line + a dot per game colored green (beat the line
    in the play's direction) or red (missed)."""
    if not values or line_value is None:
        return '<span style="color:#4a4a4a;font-size:11px;">no data</span>'

    vmin = min(values + [line_value])
    vmax = max(values + [line_value])
    rng = (vmax - vmin) or 1
    pad = 3
    n = len(values)
    step = (width - 2 * pad) / max(n - 1, 1)

    def y_of(v):
        return height - pad - ((v - vmin) / rng) * (height - 2 * pad)

    points, dots = [], []
    for i, v in enumerate(values):
        x = pad + i * step
        y = y_of(v)
        points.append(f"{x:.1f},{y:.1f}")
        beat = (v > line_value) if direction == "over" else (v < line_value)
        color = "#4CAF7D" if beat else "#E1615A"
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2" fill="{color}" />')

    line_y = y_of(line_value)
    polyline = f'<polyline points="{" ".join(points)}" fill="none" stroke="#8B8F94" stroke-width="1.3" />'
    ref_line = (f'<line x1="{pad}" y1="{line_y:.1f}" x2="{width - pad}" y2="{line_y:.1f}" '
                f'stroke="#E3A33966" stroke-width="1" stroke-dasharray="2,2" />')
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">{ref_line}{polyline}{"".join(dots)}</svg>'


def build_props_html(rows: list) -> str:
    """rows: list of dicts, each with player, team, opponent, opp_logo,
    sport, stat, line, play, sparkline_svg, projected, edge_pct, hit_rate,
    matchup, odds, status, actual. Returns a full standalone HTML doc for
    st.components.v1.html — includes its own styling (matches the app's
    black/gold glass theme) and a small click-to-sort script."""

    def esc(v):
        return "" if v is None else str(v).replace('"', "&quot;")

    body_rows = []
    for r in rows:
        team_logo_html = f'<img src="{r["team_logo"]}" style="width:22px;height:22px;object-fit:contain;vertical-align:middle;margin-right:8px;">' if r.get("team_logo") else ""
        opp_logo_html = f'<img src="{r["opp_logo"]}" style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:4px;">' if r.get("opp_logo") else ""
        result_color = {"HIT": "#3ecf8e", "MISS": "#ff5c5c", "PENDING": "#6b6b6b", "NO BET": "#8a7d55"}.get(r.get("status"), "#6b6b6b")
        body_rows.append(f"""
<tr>
  <td data-val="{esc(r['date'])}">{esc(r['date'])}</td>
  <td data-val="{esc(r['game'])}">{esc(r['game'])}</td>
  <td data-val="{esc(r['player'])}">{team_logo_html}<b style="color:#fff;">{esc(r['player'])}</b><div style="color:#6b6b6b;font-size:11px;margin-left:{'30px' if team_logo_html else '0'};">{esc(r['team'])}</div></td>
  <td data-val="{esc(r['opponent'])}">{opp_logo_html}{esc(r['opponent'])}</td>
  <td data-val="{esc(r['sport'])}">{esc(r['sport']).upper()}</td>
  <td data-val="{esc(r['stat'])}">{esc(r['stat']).upper()} {r['line']}</td>
  <td data-val="{esc(r['play'])}">{r['play']}</td>
  <td data-val="{r.get('edge_pct') or 0}">{r['sparkline_svg']}</td>
  <td data-val="{r.get('projected') or 0}">{r['projected'] if r.get('projected') is not None else '—'}</td>
  <td data-val="{r.get('edge_pct') or 0}" style="color:#E3A339;font-weight:600;font-family:'IBM Plex Mono',monospace;">{f"{abs(r['edge_pct']):.1f}%" if r.get('edge_pct') is not None else '—'}</td>
  <td data-val="{r.get('hit_rate') or 0}">{f"{r['hit_rate']:.0f}%" if r.get('hit_rate') is not None else '—'}</td>
  <td data-val="{r.get('matchup') or 0}">{f"{r['matchup']:.2f}" if r.get('matchup') is not None else '—'}</td>
  <td data-val="{esc(r['odds'])}">{esc(r['odds'])}</td>
  <td data-val="{esc(r['status'])}" style="color:{result_color};font-weight:700;">{esc(r['status'])}</td>
</tr>""")

    headers = [
        ("Date", "text", False), ("Game", "text", False),
        ("Player", "text", False), ("Opp", "text", False), ("Sport", "text", False),
        ("Stat / Line", "text", False), ("Play", "text", False), ("Last 10", "num", True),
        ("Proj", "num", True), ("Edge %", "num", True), ("Hit Rate", "num", True),
        ("Matchup", "num", True), ("Odds", "text", False), ("Result", "text", False),
    ]
    header_html = "".join(
        f'<th onclick="cpSort({i},\'{t}\')" style="cursor:pointer;user-select:none;">{label} <span style="opacity:0.4;">⇅</span></th>'
        for i, (label, t, sortable) in enumerate(headers)
    )

    return f"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
  html, body {{ height:100%; margin:0; background:transparent; font-family:'Inter',sans-serif; }}
  .cp-glass-wrap {{
    background: #14171B;
    border: 1px solid #23272C; border-radius: 8px;
    height: 100%;
  }}
  /* FIXED 2026-07-20: this used to be overflow:hidden on the same
     element as the table, which CLIPPED any column past the visible
     edge instead of letting you scroll to it — "can't slide over to
     see the rest of the table" was this, not a missing swipe gesture.
     Scroll now lives on its own inner wrapper (rounded corners stay
     on the outer .cp-glass-wrap since that one still clips cleanly at
     its own edges); -webkit-overflow-scrolling gives iOS Safari
     native momentum scrolling instead of the janky default. */
  /* FIXED 2026-07-20 (round 2): thead th's position:sticky below was
     declared but INERT — .cp-scroll-wrap had no bounded height, so it
     just grew to fit the whole table and the OUTER iframe/page ended
     up doing the scrolling instead. Sticky only works relative to its
     nearest actual scrolling ancestor — giving this wrapper a real
     max-height + overflow-y makes IT that ancestor, so the header now
     genuinely stays put while the rows scroll underneath it. */
  .cp-scroll-wrap {{
    overflow-x: auto; overflow-y: auto; height: 100%;
    -webkit-overflow-scrolling: touch; border-radius: 16px;
  }}
  table {{ width:100%; min-width:900px; border-collapse:collapse; font-size:13px; }}
  thead th {{
    background: #14171B; color:#8B8F94; font-family:'Oswald',sans-serif; font-weight:600;
    font-size:10px; letter-spacing:1px; text-transform:uppercase; text-align:left;
    padding:12px 14px; border-bottom:1px solid #23272C; position:sticky; top:0; z-index:2;
    transition: color 0.15s ease;
  }}
  thead th:hover {{ color:#E3A339; }}
  tbody td {{ padding:10px 14px; border-bottom:1px solid #1A1D21; color:#ECECE6; white-space:nowrap; }}
  tbody tr {{ transition: background 0.15s ease; }}
  tbody tr:hover {{ background: rgba(227,163,57,0.05); }}
</style></head>
<body>
<div class="cp-glass-wrap">
<div class="cp-scroll-wrap">
<table id="cpPropsTable">
  <thead><tr>{header_html}</tr></thead>
  <tbody>{"".join(body_rows)}</tbody>
</table>
</div>
</div>
<script>
function cpSort(colIndex, type) {{
  const table = document.getElementById('cpPropsTable');
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.rows);
  const header = table.tHead.rows[0].cells[colIndex];
  const asc = header.getAttribute('data-order') !== 'asc';
  rows.sort((a, b) => {{
    let av = a.cells[colIndex].getAttribute('data-val');
    let bv = b.cells[colIndex].getAttribute('data-val');
    if (type === 'num') {{ av = parseFloat(av) || 0; bv = parseFloat(bv) || 0; }}
    if (av < bv) return asc ? -1 : 1;
    if (av > bv) return asc ? 1 : -1;
    return 0;
  }});
  rows.forEach(r => tbody.appendChild(r));
  Array.from(table.tHead.rows[0].cells).forEach(c => c.removeAttribute('data-order'));
  header.setAttribute('data-order', asc ? 'asc' : 'desc');
}}
</script>
</body></html>
"""


# ---------- STYLE: Culture & Pulse Boardroom/ESPN brand — glass-card sportsbook aesthetic ----------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
    --cp-ink: #0A0C0F;
    --cp-panel: #171B20;
    --cp-line: #2A2F36;
    --cp-ember: #E3A339;
    --cp-win: #4CAF7D;
    --cp-loss: #E1615A;
    --cp-text: #ECECE6;
    --cp-mute: #8B8F94;
}

div[data-testid="stExpander"] {
    background: var(--cp-panel) !important;
    border: 1px solid var(--cp-line) !important;
    border-radius: 6px !important;
    margin-bottom: 8px !important;
    overflow: hidden;
}
div[data-testid="stExpander"]:hover {
    border-color: var(--cp-ember) !important;
}
div[data-testid="stExpander"] summary {
    padding: 12px 14px !important;
    display: flex !important;
    align-items: center !important;
    gap: 8px !important;
}
div[data-testid="stExpander"] summary,
div[data-testid="stExpander"] summary p {
    font-family: 'Oswald', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: var(--cp-text) !important;
}
div[data-testid="stExpander"] summary:hover,
div[data-testid="stExpander"] summary:hover p,
div[data-testid="stExpander"] summary:hover span {
    color: var(--cp-ember) !important;
}
div[data-testid="stExpander"] > div:nth-child(2) {
    border-top: 1px solid var(--cp-line) !important;
}

.stApp {
    background: var(--cp-ink);
}
#MainMenu, footer, header { visibility: hidden; }
* { font-family: 'Inter', -apple-system, sans-serif; }
/* Previous fix didn't work: restoring the icon's font only helps if
   that font is actually loaded — it isn't (only Oswald/Inter/IBM Plex
   Mono are imported above), so the ligature text still prints as raw
   letters. Fix: hide the native icon completely and draw our own
   arrow with CSS, so nothing depends on an icon font loading. */
div[data-testid="stExpander"] summary svg,
div[data-testid="stExpander"] summary [data-testid*="Icon"],
div[data-testid="stExpander"] summary [class*="Icon"] {
    display: none !important;
}
div[data-testid="stExpander"] summary::before {
    content: "▶";
    font-family: inherit !important;
    font-size: 10px;
    color: var(--cp-mute);
    transition: transform 0.15s ease;
    flex-shrink: 0;
}
div[data-testid="stExpander"] details[open] summary::before {
    transform: rotate(90deg);
}
.cp-card .record, .cp-overall .value, .cp-ticker .stat-val, .cp-card .pct-up, .cp-card .pct-down {
    font-family: 'IBM Plex Mono', monospace !important;
}

.cp-header { display: flex; align-items: center; justify-content: space-between; padding: 4px 0 22px 0; margin-bottom: 10px; border-bottom: 1px solid rgba(212,175,55,0.14); position: relative; }
.cp-header::after { content: ""; position: absolute; bottom: -1px; left: 0; width: 140px; height: 1px; background: linear-gradient(90deg, #D4AF37, transparent); }
.cp-header .brand { display: flex; align-items: center; gap: 10px; }
.cp-header .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--cp-ember); animation: cp-pulse 2s ease-in-out infinite; }
@keyframes cp-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.cp-header h1 { font-family: 'Oswald', sans-serif; font-size: 28px; font-weight: 600; color: var(--cp-text); margin: 0; letter-spacing: 0.3px; }
.cp-header .sub { font-family: 'Inter', sans-serif; color: var(--cp-mute); font-size: 11px; font-weight: 500; letter-spacing: 1.5px; text-transform: uppercase; }

.cp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; margin-bottom: 22px; }
.cp-card {
    background: var(--cp-panel);
    border: 1px solid var(--cp-line);
    border-radius: 6px; padding: 14px 16px; position: relative;
    transition: border-color 0.15s ease;
}
.cp-card:hover { border-color: var(--cp-ember); }
.cp-card .sport-name { font-family: 'Oswald', sans-serif; color: var(--cp-mute); font-size: 10px; font-weight: 600; letter-spacing: 1.2px; text-transform: uppercase; margin-bottom: 6px; }
.cp-card .record { color: var(--cp-text); font-size: 22px; font-weight: 600; line-height: 1; letter-spacing: 0; }
.cp-card .pct-row { display: flex; align-items: center; gap: 5px; margin-top: 9px; }
.cp-card .pct-up { color: #3ecf8e; font-size: 13px; font-weight: 700; }
.cp-card .pct-down { color: #ff5c5c; font-size: 13px; font-weight: 700; }

.cp-overall {
    background: var(--cp-panel);
    border: 1px solid var(--cp-line); border-left: 3px solid var(--cp-ember);
    border-radius: 6px; padding: 16px 20px; margin-bottom: 22px;
}
.cp-overall .label { font-family: 'Oswald', sans-serif; color: var(--cp-mute); font-size: 10px; letter-spacing: 1.2px; text-transform: uppercase; margin-bottom: 5px; font-weight: 600; }
.cp-overall .value { color: var(--cp-text); font-size: 24px; font-weight: 600; letter-spacing: 0; }
.cp-overall .value .pct { color: var(--cp-ember); }

.tier-green { background: rgba(76,175,125,0.12); color: var(--cp-win); padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 600; border: 1px solid rgba(76,175,125,0.3); font-family:'IBM Plex Mono',monospace; }
.tier-yellow { background: rgba(227,163,57,0.12); color: var(--cp-ember); padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 600; border: 1px solid rgba(227,163,57,0.3); font-family:'IBM Plex Mono',monospace; }

.cp-ticker { display: flex; align-items: stretch; padding: 0; background: var(--cp-panel); border: 1px solid var(--cp-line); border-radius: 6px; margin-bottom: 16px; overflow: hidden; }
.cp-ticker .stat-group { display: flex; gap: 0; flex: 1; flex-wrap: wrap; }
.cp-ticker .stat-group > span { flex: 1; padding: 10px 18px; border-right: 1px solid var(--cp-line); }
.cp-ticker .stat-group > span:last-child { border-right: none; }
.cp-ticker .stat-lbl { display:block; font-family: 'Oswald', sans-serif; color: var(--cp-mute); font-size: 9px; font-weight: 600; letter-spacing: 1.2px; text-transform: uppercase; margin-bottom: 3px; }
.cp-ticker .stat-val { color: var(--cp-text); font-weight: 600; font-size: 16px; font-family: 'IBM Plex Mono', monospace; }
.cp-pill { background: rgba(227,163,57,0.1); border: 1px solid rgba(227,163,57,0.3); color: var(--cp-ember); font-size: 10px; font-weight: 600; padding: 3px 10px; border-radius: 3px; font-family:'IBM Plex Mono',monospace; }
.stButton button,
button[kind="secondary"],
div[data-testid="stButton"] button {
    background: var(--cp-panel) !important;
    border: 1px solid var(--cp-line) !important;
    color: var(--cp-ember) !important;
    font-family: 'Oswald', sans-serif !important;
    font-size: 11px !important;
    font-weight: 600 !important;
    padding: 4px 14px !important;
    border-radius: 4px !important;
    width: auto !important;
    min-height: 0 !important;
}
.stButton button:hover,
button[kind="secondary"]:hover,
div[data-testid="stButton"] button:hover {
    background: rgba(227,163,57,0.1) !important;
    border-color: var(--cp-ember) !important;
    color: var(--cp-ember) !important;
}
.stButton button p,
div[data-testid="stButton"] button p {
    color: inherit !important;
    font-family: inherit !important;
}

h3 { font-family: 'Oswald', sans-serif !important; color: #8a7d55 !important; font-weight: 600 !important; font-size: 14px !important; text-transform: uppercase; letter-spacing: 1.5px; }

.stMultiSelect label p, .stSlider label p, .stTextInput label p, .stDateInput label p {
    font-family: 'Oswald', sans-serif !important; color: #8a7d55 !important; font-size: 11px !important;
    font-weight: 600 !important; letter-spacing: 1.5px !important; text-transform: uppercase;
}

section[data-testid="stDataFrame"] {
    border-radius: 14px; overflow: hidden; border: 1px solid rgba(212,175,55,0.14);
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
}
.stMultiSelect [data-baseweb="tag"] { background-color: rgba(212,175,55,0.14) !important; color: #D4AF37 !important; border: 1px solid rgba(212,175,55,0.25) !important; }
.stMultiSelect > div > div, .stTextInput > div > div, .stDateInput > div > div {
    background-color: rgba(19,18,9,0.6) !important; backdrop-filter: blur(10px);
    border: 1px solid rgba(212,175,55,0.14) !important; border-radius: 10px !important;
    transition: border-color 0.18s ease;
}
.stMultiSelect > div > div:focus-within, .stTextInput > div > div:focus-within {
    border-color: rgba(212,175,55,0.6) !important;
}
.stTextInput input { color: #ffffff !important; }
div[data-testid="stSlider"] [data-baseweb="slider"] { background: var(--cp-line) !important; }
div[data-testid="stSlider"] [data-baseweb="slider"] > div { background: var(--cp-line) !important; }
div[data-testid="stSlider"] [data-baseweb="slider"] > div > div { background: var(--cp-ember) !important; }
div[data-testid="stSlider"] [role="slider"] { background-color: var(--cp-ember) !important; border-color: var(--cp-ember) !important; box-shadow: none !important; }
div[data-testid="stSlider"] [role="slider"] div { background-color: var(--cp-ember) !important; color: var(--cp-ink) !important; }
div[data-testid="stSliderThumbValue"] { color: var(--cp-ember) !important; }
div[data-testid="stTickBarMin"], div[data-testid="stTickBarMax"] { color: var(--cp-mute) !important; }
div[data-testid="stSlider"] * { border-color: var(--cp-ember) !important; }

hr { border-color: rgba(212,175,55,0.14) !important; margin: 22px 0 !important; }

.stTabs [data-baseweb="tab-list"] { gap: 20px; border-bottom: 1px solid var(--cp-line); }
.stTabs [data-baseweb="tab"] {
    background-color: transparent;
    border: none; border-radius: 0;
    color: var(--cp-mute); font-family: 'Oswald', sans-serif; font-size: 13px; letter-spacing: 0.3px; padding: 0 0 10px;
    transition: color 0.15s ease;
}
.stTabs [data-baseweb="tab"]:hover { color: var(--cp-ember); background-color: transparent; }
.stTabs [aria-selected="true"] { color: var(--cp-ember) !important; border-bottom: 2px solid var(--cp-ember) !important; background-color: transparent !important; }

div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column"] { gap: 0.5rem; }
.block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load_picks():
    """Prediction Engine v2 (2026-07-20): predictions can now hold up
    to 3 rows per game (moneyline/spread/total), so this now pulls
    market, pick, line, and the projected-score columns alongside the
    existing fields. Rows logged before v2 will have market defaulted
    to 'moneyline' and pick/line/projected_* as NULL — the UI below
    falls back to the old `bet` text field for those."""
    conn = get_conn()

    query = """
        SELECT p.date, p.sport, p.game, p.bet, p.odds, p.edge,
               p.model_prob, p.implied_prob, p.home_record, p.away_record,
               p.home_rest, p.away_rest, p.home_injuries, p.away_injuries,
               p.market, p.pick, p.line, p.projected_home, p.projected_away,
               p.projected_margin, p.projected_total, p.confidence,
               r.home_team, r.away_team, r.home_score, r.away_score, r.correct, r.push
        FROM predictions p
        LEFT JOIN results r ON r.prediction_id = p.id
        ORDER BY p.date DESC
    """
    cur = conn.execute(query)
    rows = cur.fetchall()
    cols = ["date", "sport", "game", "bet", "odds", "edge",
            "model_prob", "implied_prob", "home_record", "away_record",
            "home_rest", "away_rest", "home_injuries", "away_injuries",
            "market", "pick", "line", "projected_home", "projected_away",
            "projected_margin", "projected_total", "confidence",
            "result_home_team", "result_away_team", "home_score", "away_score", "correct", "push"]
    df = pd.DataFrame(rows, columns=cols)
    # Old rows logged before v2 have market=NULL in the DB only if they
    # predate the DEFAULT 'moneyline' on the column — normalize here too
    # so filters/grouping never see a blank market.
    if not df.empty:
        df["market"] = df["market"].fillna("moneyline")
    return df


@st.cache_data(ttl=300)
def load_rankings(sport: str):
    """Wraps ranking_engine.get_rankings() — pure compute, no stored
    table, so this just caches the live result for 5 minutes instead
    of recomputing on every rerun."""
    try:
        return ranking_engine.get_rankings(sport)
    except Exception:
        return []


@st.cache_data(ttl=600)
def load_player_list(sport: str) -> list:
    """Distinct player names with recent data for this sport, for the
    Player Profiles browse dropdown. Pulls from BOTH the game log table
    (real box-score history) and player_props (current lines) since a
    player can have one without the other early/late in a slate — union
    catches anyone with either. Sorted alphabetically. 10-minute cache
    since rosters don't change minute to minute."""
    table = GAME_LOG_TABLES.get(sport)
    names = set()
    try:
        conn = get_conn()
        if table:
            cur = conn.execute(f"SELECT DISTINCT player_name FROM {table}")
            names.update(r[0] for r in cur.fetchall() if r[0])
        cur = conn.execute(
            "SELECT DISTINCT player_name FROM player_props WHERE sport = ?",
            (sport,),
        )
        names.update(r[0] for r in cur.fetchall() if r[0])
    except Exception:
        return []
    return sorted(names)


@st.cache_data(ttl=300)
def load_performance_summary(period: str, sport: str = None):
    """Wraps performance_tracker's summary generators. period is
    'today' | 'week' | 'season'."""
    try:
        if period == "season":
            record = performance_tracker.calculate_record(sport=sport)
            roi = performance_tracker.calculate_roi(sport=sport)
            by_sport = performance_tracker.calculate_record_by_sport()
            best_worst = performance_tracker.get_best_worst_pick()
            buckets = performance_tracker.calculate_confidence_buckets()
        elif period == "week":
            from datetime import datetime, timedelta
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
            date_range = (start, end)
            record = performance_tracker.calculate_record(date_range=date_range, sport=sport)
            roi = performance_tracker.calculate_roi(date_range=date_range, sport=sport)
            by_sport = performance_tracker.calculate_record_by_sport(date_range=date_range)
            best_worst = performance_tracker.get_best_worst_pick(date_range=date_range)
            buckets = performance_tracker.calculate_confidence_buckets(date_range=date_range)
        else:  # today
            from datetime import datetime
            today = datetime.now().strftime("%Y-%m-%d")
            record = performance_tracker.calculate_record(date=today, sport=sport)
            roi = performance_tracker.calculate_roi(date=today, sport=sport)
            by_sport = performance_tracker.calculate_record_by_sport(date=today)
            best_worst = performance_tracker.get_best_worst_pick(date=today)
            buckets = performance_tracker.calculate_confidence_buckets(date=today)
        return {
            "record": record, "roi": roi, "by_sport": by_sport,
            "best_pick": best_worst["best"], "worst_pick": best_worst["worst"],
            "highest_confidence_pick": best_worst["highest_confidence_pick"],
            "confidence_buckets": buckets,
        }
    except Exception:
        return None


# ---------- HEADER ----------
st.markdown("""
<div class="cp-header">
    <div class="brand">
        <div class="dot"></div>
        <div>
            <h1>Culture & Pulse Picks</h1>
            <div class="sub">Live Model Performance Tracking</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


from market_status import is_visible, show_confidence

tab_games, tab_props, tab_edge, tab_players, tab_rankings, tab_betting = st.tabs(
    ["Game Picks", "Player Props", "Edge Finder", "Player Profiles", "Power Rankings", "Betting Analytics"]
)

# =========================================================
# TAB 1: GAME PICKS
# =========================================================
with tab_games:
    df = load_picks()

    if df.empty:
        st.warning("No picks found.")
    else:
        df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce")
        df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce")
        df["correct"] = pd.to_numeric(df["correct"], errors="coerce")
        # push column only exists once results.push has been added
        # (Prediction Engine v2 grading) — older rows/deployments
        # without it just show pd.NA here, which reads as "not a push"
        # everywhere below.
        if "push" not in df.columns:
            df["push"] = False
        df["push"] = df["push"].fillna(False).astype(bool)

        def status(row):
            if row["push"]:
                return "PUSH"
            if pd.isna(row["correct"]):
                return "PENDING"
            return "WIN" if row["correct"] == 1 else "LOSS"
        df["status"] = df.apply(status, axis=1)

        def build_score(row):
            if pd.isna(row["home_score"]) or pd.isna(row["away_score"]):
                return ""
            return f"{row['result_away_team'] or ''} {int(row['away_score'])} - {int(row['home_score'])} {row['result_home_team'] or ''}"
        df["final_score"] = df.apply(build_score, axis=1)

        # ---------- DATE RANGE FILTER (applies to everything below: cards, streaks, table) ----------
        df["date_parsed"] = pd.to_datetime(df["date"], errors="coerce")
        min_date = df["date_parsed"].min()
        max_date = df["date_parsed"].max()

        date_range = st.date_input(
            "Date range",
            value=(min_date.date(), max_date.date()) if pd.notna(min_date) else None,
            min_value=min_date.date() if pd.notna(min_date) else None,
            max_value=max_date.date() if pd.notna(max_date) else None,
            key="g_date_range",
        )
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start, end = date_range
            df = df[(df["date_parsed"].dt.date >= start) & (df["date_parsed"].dt.date <= end)]

        def current_streak(group):
            """Count consecutive WIN or LOSS from most recent game backward."""
            ordered = group.sort_values("date_parsed", ascending=False)
            statuses = ordered["status"].tolist()
            if not statuses or statuses[0] == "PENDING":
                return None
            streak_type = statuses[0]
            count = 0
            for s in statuses:
                if s == streak_type:
                    count += 1
                else:
                    break
            return (streak_type, count)

        streaks = {}
        for sport, group in df[df["status"].isin(["WIN", "LOSS"])].groupby("sport"):
            streaks[sport] = current_streak(group)

        settled = df[df["status"].isin(["WIN", "LOSS"])]
        summary = settled.groupby("sport")["status"].value_counts().unstack(fill_value=0)

        if not summary.empty:
            summary["total"] = summary.get("WIN", 0) + summary.get("LOSS", 0)
            summary["win_pct"] = (summary.get("WIN", 0) / summary["total"] * 100).round(1)

            overall_wins = int(summary.get("WIN", pd.Series(dtype=int)).sum())
            overall_losses = int(summary.get("LOSS", pd.Series(dtype=int)).sum())
            overall_total = overall_wins + overall_losses
            overall_pct = round(overall_wins / overall_total * 100, 1) if overall_total else 0

            # Today's edge count — how many picks are dated today,
            # regardless of settled/pending status.
            today_ct = pd.Timestamp.now().strftime("%Y-%m-%d")
            todays_edge_count = int((df["date"] == today_ct).sum())

            # Season ROI — reuses performance_tracker the same way the
            # Betting Analytics tab already does. Wrapped defensively so
            # a ticker render never breaks if ROI can't be computed
            # (e.g. no odds on record yet).
            roi_str = "—"
            try:
                roi_data = performance_tracker.calculate_roi()
                if roi_data.get("roi_pct") is not None:
                    sign = "+" if roi_data["roi_pct"] >= 0 else ""
                    roi_str = f"{sign}{roi_data['roi_pct']}%"
            except Exception:
                pass

            st.markdown(
                f'<div class="cp-ticker">'
                f'<div class="stat-group">'
                f'<span><span class="stat-lbl">Season</span>'
                f'<span class="stat-val">{overall_wins}-{overall_losses} '
                f'<span style="color:#D4AF37;">{overall_pct}%</span></span></span>'
                f'<span><span class="stat-lbl">Today</span>'
                f'<span class="stat-val">{todays_edge_count} edges</span></span>'
                f'<span><span class="stat-lbl">ROI</span>'
                f'<span class="stat-val" style="color:#3ecf8e;">{roi_str}</span></span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            # Natural-width columns sized to content instead of one
            # column per sport stretched full-width — spacer column
            # absorbs leftover width so pills stay compact and
            # left-clustered rather than spread across the page.
            n_sports = len(summary.index)
            pill_cols = st.columns([1] * n_sports + [6])
            for i, s in enumerate(summary.index):
                with pill_cols[i]:
                    label = s.upper()
                    streak = streaks.get(s)
                    if streak and st.session_state.get("g_streak_sport") == s:
                        s_type, s_count = streak
                        s_letter = "W" if s_type == "WIN" else "L"
                        label = f"{s.upper()} {s_letter}{s_count}"
                    if st.button(label, key=f"streak_pill_{s}"):
                        st.session_state["g_streak_sport"] = (
                            None if st.session_state.get("g_streak_sport") == s else s
                        )

            # ---------- BEST / WORST PICK HIGHLIGHT ----------
            wins = settled[settled["status"] == "WIN"]
            losses = settled[settled["status"] == "LOSS"]
            best = wins.loc[wins["edge"].idxmax()] if not wins.empty else None
            worst = losses.loc[losses["edge"].idxmax()] if not losses.empty else None

            hl_cols = st.columns(2)
            if best is not None:
                with hl_cols[0]:
                    st.markdown(f"""
<div class="cp-card" style="border-left:3px solid #3ecf8e;">
<div class="sport-name">Best pick &middot; {best['sport']}</div>
<div style="color:#fff;font-weight:700;font-size:15px;margin-top:4px;">{pick_display(best)}</div>
<div style="color:#8a7d55;font-size:12px;margin-top:4px;">{best['game']} &middot; {best['date']}</div>
<div style="color:#3ecf8e;font-weight:800;font-size:14px;margin-top:8px;">+{best['edge']}% edge &middot; WIN</div>
</div>
""", unsafe_allow_html=True)
            if worst is not None:
                with hl_cols[1]:
                    st.markdown(f"""
<div class="cp-card" style="border-left:3px solid #ff5c5c;">
<div class="sport-name">Worst pick &middot; {worst['sport']}</div>
<div style="color:#fff;font-weight:700;font-size:15px;margin-top:4px;">{pick_display(worst)}</div>
<div style="color:#8a7d55;font-size:12px;margin-top:4px;">{worst['game']} &middot; {worst['date']}</div>
<div style="color:#ff5c5c;font-weight:800;font-size:14px;margin-top:8px;">+{worst['edge']}% edge &middot; LOSS</div>
</div>
""", unsafe_allow_html=True)
        else:
            st.info("No settled picks yet.")

        # Reserved slot for the clicked-game detail card — filled in further
        # down after we know which row (if any) got selected in the table.
        detail_slot = st.empty()

        st.markdown("---")
        fc1, fc2, fc3, fc4, fc5 = st.columns([1, 1, 1, 1, 1.3])
        with fc1:
            sport_filter = st.multiselect("Sport", options=df["sport"].unique(), default=list(df["sport"].unique()), key="g_sport")
        with fc2:
            market_filter = st.multiselect(
                "Market",
                options=sorted(df["market"].unique()),
                default=sorted(df["market"].unique()),
                format_func=market_label,
                key="g_market",
            )
        with fc3:
            status_filter = st.multiselect("Result", options=["WIN", "LOSS", "PUSH", "PENDING"], default=["WIN", "LOSS", "PUSH", "PENDING"], key="g_status")
        with fc4:
            min_edge_g = st.slider("Min Edge %", 0.0, 50.0, 0.0, 1.0, key="g_edge")
        with fc5:
            search_g = st.text_input("Search team/game", "", key="g_search")

        filtered = df[
            df["sport"].isin(sport_filter)
            & df["market"].isin(market_filter)
            & df["status"].isin(status_filter)
        ].copy()
        # market_status.py gate: never show a sport+market combo marked OFF
        # (e.g. MLB), regardless of what the Sport/Market filters above allow.
        filtered = filtered[
            filtered.apply(lambda r: is_visible(r["sport"], r["market"]), axis=1)
        ]
        filtered["edge"] = pd.to_numeric(filtered["edge"], errors="coerce")
        filtered = filtered[(filtered["edge"].abs() >= min_edge_g) | filtered["edge"].isna()]
        if search_g:
            filtered = filtered[filtered["game"].str.contains(search_g, case=False, na=False)
                                 | filtered["bet"].str.contains(search_g, case=False, na=False)
                                 | filtered["pick"].fillna("").str.contains(search_g, case=False, na=False)]

        # Same 15% / 7% edge thresholds used by the projection engine's
        # confidence tiers elsewhere in the app, applied here to game picks
        # so both tabs read the same way at a glance.
        def edge_tier(edge):
            if pd.isna(edge):
                return "—"
            pct = abs(edge)
            if pct >= 15:
                return "🟢"
            if pct >= 7:
                return "🟡"
            return "🔴"
        filtered["Tier"] = filtered["edge"].apply(edge_tier)

        filtered["Market"] = filtered["market"].apply(market_label)
        filtered["Pick"] = filtered.apply(pick_display, axis=1)

        # Pull the team name being bet on out of the pick (falls back to
        # the old "bet" field for pre-v2 rows) to look up its logo — only
        # meaningful for moneyline/spread picks, not Over/Under totals.
        def pick_logo(row):
            team_guess = (row["Pick"] or "").split(" ")[0:2]
            team_guess = " ".join(team_guess) if team_guess else ""
            if row["market"] == "total":
                return ""
            team_guess = row["pick"] or row["bet"].replace(" ML", "")
            return team_logo_url(row["sport"], team_guess.strip())
        if filtered.empty:
            filtered["pick_logo"] = pd.Series(dtype=str)
        else:
            filtered["pick_logo"] = filtered.apply(pick_logo, axis=1)

        sorted_full = filtered.sort_values("date", ascending=False).reset_index(drop=True)
        st.write(f"**{len(sorted_full)} picks**")
        display_cols = ["pick_logo", "date", "sport", "game", "Market", "Pick", "Tier", "odds", "edge", "final_score", "status"]

        event = st.dataframe(
            sorted_full[display_cols],
            width="stretch", hide_index=True, height=600,
            column_config={
                "pick_logo": st.column_config.ImageColumn(""),
                "Market": st.column_config.TextColumn("Market", width="small"),
                "Pick": st.column_config.TextColumn("Pick"),
                "Tier": st.column_config.TextColumn("Tier", width="small"),
                "status": st.column_config.TextColumn("Result"),
                "final_score": st.column_config.TextColumn("Score"),
                "edge": st.column_config.NumberColumn("Edge %", format="%.1f"),
            },
            on_select="rerun",
            selection_mode="single-row",
            key="picks_table",
        )

        if event and event.selection and event.selection.rows:
            g = sorted_full.iloc[event.selection.rows[0]]
            score_line = g["final_score"] if g["final_score"] else "Not yet played"
            status_color = {"WIN": "#3ecf8e", "LOSS": "#ff5c5c", "PUSH": "#D4AF37", "PENDING": "#8a7d55"}.get(g["status"], "#8a7d55")

            # All markets logged for this same game/date — lets the detail
            # card show ML + Spread + Total together like a sportsbook
            # matchup card, instead of only the one row that was clicked.
            game_markets = df[(df["date"] == g["date"]) & (df["game"] == g["game"])].copy()

            market_cards = []
            for _, m in game_markets.sort_values("market").iterrows():
                m_status = m["status"] if "status" in m else (
                    "WIN" if m["correct"] == 1 else "LOSS" if m["correct"] == 0 else "PENDING"
                )
                m_color = {"WIN": "#3ecf8e", "LOSS": "#ff5c5c", "PUSH": "#D4AF37", "PENDING": "#8a7d55"}.get(m_status, "#8a7d55")
                if show_confidence(m["sport"], m["market"]):
                    m_prob = f"{m['model_prob']:.1f}%" if pd.notna(m["model_prob"]) else "—"
                else:
                    m_prob = "Beta"
                market_cards.append(f"""
<div style="background:rgba(19,18,9,0.5);border:1px solid rgba(212,175,55,0.12);border-radius:10px;padding:12px 16px;min-width:150px;">
<div class="label" style="margin-bottom:4px;">{market_label(m['market'])}</div>
<div style="color:#fff;font-weight:700;font-size:14px;">{pick_display(m)}</div>
<div style="color:#8a7d55;font-size:11px;margin-top:4px;">{m['odds']} &middot; {m_prob} model &middot; <span style="color:{m_color};font-weight:700;">{m_status}</span></div>
</div>""")

            # Projected score block — only shows if at least one market row
            # for this game has projected_home/away populated.
            proj_row = game_markets[game_markets["projected_home"].notna()]
            proj_html = ""
            if not proj_row.empty:
                pr = proj_row.iloc[0]
                home_nm = g["result_home_team"] or g["game"].split(" @ ")[-1]
                away_nm = g["result_away_team"] or g["game"].split(" @ ")[0]
                proj_html = f"""
<div style="margin-top:14px;padding-top:14px;border-top:1px solid rgba(212,175,55,0.14);">
<div class="label" style="margin-bottom:8px;">Model Projection</div>
<div style="display:flex;gap:24px;flex-wrap:wrap;">
<div><div style="color:#8a7d55;font-size:11px;">{away_nm}</div><div style="color:#fff;font-size:18px;font-weight:800;">{pr['projected_away']:.1f}</div></div>
<div><div style="color:#8a7d55;font-size:11px;">{home_nm}</div><div style="color:#fff;font-size:18px;font-weight:800;">{pr['projected_home']:.1f}</div></div>
<div><div style="color:#8a7d55;font-size:11px;">Margin</div><div style="color:#D4AF37;font-size:18px;font-weight:800;">{pr['projected_margin']:+.1f}</div></div>
<div><div style="color:#8a7d55;font-size:11px;">Total</div><div style="color:#D4AF37;font-size:18px;font-weight:800;">{pr['projected_total']:.1f}</div></div>
</div>
</div>"""

            detail_slot.markdown(f"""
<div class="cp-overall" style="border-left-color:{status_color};">
<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;">
<div>
<div class="label">{g['date']} &middot; {g['sport'].upper()}</div>
<div class="value" style="font-size:20px;">{g['game']}</div>
</div>
<div style="text-align:right;">
<div class="label">Score</div>
<div style="color:#8a7d55;font-size:13px;">{score_line}</div>
</div>
</div>
<div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:16px;padding-top:14px;border-top:1px solid rgba(212,175,55,0.14);">
{"".join(market_cards)}
</div>
{proj_html}
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px;margin-top:16px;padding-top:14px;border-top:1px solid rgba(212,175,55,0.14);">
<div><div class="label">Home record</div><div style="color:#fff;font-weight:700;">{g['home_record'] or '—'}</div></div>
<div><div class="label">Away record</div><div style="color:#fff;font-weight:700;">{g['away_record'] or '—'}</div></div>
<div><div class="label">Rest (H/A)</div><div style="color:#fff;font-weight:700;">{g['home_rest'] if pd.notna(g['home_rest']) else '—'}d / {g['away_rest'] if pd.notna(g['away_rest']) else '—'}d</div></div>
</div>
</div>
""", unsafe_allow_html=True)
        else:
            detail_slot.info("Click a game in the table below to see full details.")

# =========================================================
# TAB 2: PLAYER PROPS
# =========================================================
with tab_props:
    try:
        props_df = load_props.load_props()
    except Exception as e:
        st.error("load_props failed")
        st.exception(e)
        st.stop()

    def prop_status(row):
        if row.get("result_status") == "NO_BET":
            return "NO BET"
        if pd.isna(row["hit"]):
            return "PENDING"
        return "HIT" if row["hit"] == 1 else "MISS"
    props_df["status"] = props_df.apply(prop_status, axis=1)

    settled_props = props_df[props_df["status"].isin(["HIT", "MISS"])]
    if not settled_props.empty:
        hits = int((settled_props["status"] == "HIT").sum())
        total = len(settled_props)
        hit_pct = round(hits / total * 100, 1) if total else 0
        _, grade_color = grade_from_pct(hit_pct)  # keep color-coding, swap the letter for the real number
        st.markdown(
            f'<div class="cp-overall"><div class="label">Props Record</div>'
            f'<div class="value">{hits}-{total - hits} '
            f'<span class="pct" style="color:{grade_color};font-weight:800;">· {hit_pct}%</span></div></div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No settled props yet.")

    st.markdown("---")

    # ── filter row ──
    fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1.5])
    with fc1:
        sport_f = st.multiselect("Sport", options=props_df["sport"].unique(), default=list(props_df["sport"].unique()), key="p_sport")
    with fc2:
        status_f = st.multiselect("Result", options=["HIT", "MISS", "PENDING", "NO BET"], default=["HIT", "MISS", "PENDING"], key="p_status")
    with fc3:
        min_edge = st.slider("Min Edge %", 0.0, 50.0, 8.0, 1.0, key="p_edge")
    with fc4:
        search = st.text_input("Search player", "", key="p_search")

    pf = props_df[
        props_df["sport"].isin(sport_f)
        & props_df["status"].isin(status_f)
    ].copy()

    if "projection_edge_pct" in pf.columns:
        pf = pf[
            (pf["projection_edge_pct"].abs() >= min_edge)
            | pf["projection_edge_pct"].isna()
        ]

    if search:
        pf = pf[
            pf["player_name"].str.contains(
                search,
                case=False,
                na=False
            )
        ]

    st.write(f"**{len(pf)} props**")

    if pf.empty:
        st.info("No props match these filters.")
    else:
        tier_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}

        def play_label(row):
            tier = row.get("projection_tier")
            direction = row.get("projection_direction")
            tier = tier.lower() if isinstance(tier, str) else ""
            direction = direction.upper() if isinstance(direction, str) else ""
            if tier and direction:
                return f"{tier_emoji.get(tier, '')} {direction}"
            # fall back to the old hit-rate-based tier for rows saved
            # before the projection engine existed
            old_tier = row.get("confidence_tier")
            old_tier = old_tier.lower() if isinstance(old_tier, str) else ""
            if "🟢" in old_tier or old_tier == "green":
                return "🟢 —"
            if "🟡" in old_tier or old_tier == "yellow":
                return "🟡 —"
            return "—"

        display = pf.copy()
        display["Play"] = display.apply(play_label, axis=1)
        display["Odds"] = display.apply(
            lambda x: f"o{x['over_odds']}/u{x['under_odds']}" if pd.notna(x.get("over_odds")) else "—", axis=1
        )
        display["opp_logo"] = display.apply(lambda x: team_logo_url(x["sport"], x["opponent"]), axis=1)
        display["team_logo"] = display.apply(lambda x: team_logo_url(x["sport"], x["team_name"]), axis=1)
        # Default sort: date, then game (team+opponent), then player's own
        # team — matches how Drew organizes props for posting. Edge % is
        # still fully available by clicking that column header.
        display = display.sort_values(
            ["date", "team_name", "opponent"], ascending=[False, True, True]
        )

        # ---- BATCHED sparkline fetch: one query per (sport, stat) pair
        # instead of one query per row. Build the lookup dict first, then
        # the row loop below just does dict lookups (no DB calls).
        recent_lookup = {}
        for (sport_key, stat_key), group in display.groupby(["sport", "stat"]):
            names = tuple(group["player_name"].unique())
            recent_lookup[(sport_key, stat_key)] = get_recent_values_batch(sport_key, stat_key, names, n=10)

        table_rows = []
        for _, row in display.iterrows():
            recent = recent_lookup.get((row["sport"], row["stat"]), {}).get(row["player_name"], [])
            direction = row.get("projection_direction") or "over"
            spark = sparkline_svg(recent, row["line"], direction=direction)
            table_rows.append({
                "date": row["date"], "game": f"{row['team_name']} vs {row['opponent']}",
                "player": row["player_name"], "team": row["team_name"], "team_logo": row["team_logo"],
                "opponent": row["opponent"], "opp_logo": row["opp_logo"],
                "sport": row["sport"], "stat": row["stat"], "line": row["line"],
                "play": row["Play"], "sparkline_svg": spark,
                "projected": row.get("projected_stat") if pd.notna(row.get("projected_stat")) else None,
                "edge_pct": row.get("projection_edge_pct") if pd.notna(row.get("projection_edge_pct")) else None,
                "hit_rate": row.get("hit_rate_overall") if pd.notna(row.get("hit_rate_overall")) else None,
                "matchup": row.get("defense_factor") if pd.notna(row.get("defense_factor")) else None,
                "odds": row["Odds"], "status": row["status"],
            })

        with st.expander("ℹ️ What each column means"):
            st.markdown("""
- **Date** — game date
- **Game** — matchup (away @ home)
- **Player** — the player this prop is on, with their team below the name
- **Opp** — the opponent for this specific prop (who the player is facing)
- **Sport** — WNBA / MLB / etc.
- **Stat / Line** — the stat being bet (PTS, RBIS, HITS, etc.) and the posted line to hit
- **Play** — 🟢 Over or 🔴 Under, our model's actual recommendation
- **Last 10** — sparkline of the player's last 10 games vs. this line; green dot = beat it, red = missed it, dashed line = the line itself
- **Proj** — our model's projected value for this stat tonight
- **Edge %** — how far our projection sits from the posted line, as a percent (bigger = stronger signal either direction)
- **Hit Rate** — how often this exact play (over/under this stat) has actually hit historically
- **Matchup** — opponent's defensive strength vs. this stat: **above 1.0** = opponent allows more than league average (favorable for Over), **below 1.0** = tougher than average (favorable for Under)
- **Odds** — the over/under odds on this line
- **Result** — HIT / MISS / PENDING / NO BET once the game plays out
""")

        # Group rows by game so each matchup gets its own collapsible
        # section instead of one flat table with the game name repeated
        # on every row. Groups sorted by highest edge_pct within the
        # group, so the most interesting game-groups float visually
        # once expanded (row order inside each group, not group order,
        # since Streamlit expanders don't reorder by content easily —
        # group order stays as encountered, matching the existing
        # date/team/opponent sort).
        groups = {}
        group_order = []
        for row in table_rows:
            g = row["game"]
            if g not in groups:
                groups[g] = []
                group_order.append(g)
            groups[g].append(row)

        st.caption("👉 Swipe left/right, up/down within a game to see everything")
        for g in group_order:
            rows = groups[g]
            with st.expander(f"{g}  ·  {len(rows)} prop{'s' if len(rows) != 1 else ''}", expanded=False):
                table_height = min(72 + len(rows) * 42, 420)
                components.html(
                    build_props_html(rows),
                    height=table_height,
                    scrolling=False
                )

# =========================================================
# TAB: EDGE FINDER
# =========================================================
with tab_edge:
    st.markdown(
        '<div style="color:#8a7d55;font-size:12px;margin-bottom:14px;font-family:\'Oswald\',sans-serif;'
        'letter-spacing:1.5px;text-transform:uppercase;">Composite ranking — hit rate + projection edge + defense matchup</div>',
        unsafe_allow_html=True,
    )

    ec1, ec2, ec3 = st.columns([1, 1, 1])
    with ec1:
        edge_sport = st.selectbox("Sport", options=edge_finder.SUPPORTED_SPORTS, index=0, key="e_sport")
    with ec2:
        # Central-time "today" — matches the convention fetch_prizepicks_props.py
        # and routes_props.py use, so this defaults to the same slate the
        # live pipeline just fetched, not whatever date the server's UTC
        # clock happens to think it is.
        from datetime import datetime as _dt, timedelta as _td
        _today_ct = (_dt.utcnow() - _td(hours=5)).strftime("%Y-%m-%d")
        edge_date = st.text_input("Date (YYYY-MM-DD)", value=_today_ct, key="e_date")
    with ec3:
        edge_top_n = st.slider("Show top", 3, 20, 5, key="e_top_n")

    try:
        edge_picks = edge_finder.get_edge_finder(edge_date, sport=edge_sport, top_n=edge_top_n)
    except Exception as e:
        st.error("edge_finder.get_edge_finder failed")
        st.exception(e)
        edge_picks = []

    if not edge_picks:
        st.info(
            f"No qualifying edges for {edge_sport.upper()} on {edge_date}. "
            f"This means nothing cleared the confidence guardrails "
            f"(min {edge_finder.MIN_HIT_RATE}% hit rate, {edge_finder.MIN_EDGE_PCT}%+ edge, "
            f"{edge_finder.MIN_SAMPLE_SIZE}+ games) — not necessarily a broken query."
        )
    else:
        CONFIDENCE_COLOR = {"HIGH": "#3ecf8e", "MEDIUM": "#e8c547"}

        for i, p in enumerate(edge_picks, 1):
            conf_color = CONFIDENCE_COLOR.get(p["confidence"], "#8a7d55")
            direction_label = "Over" if p["projection_direction"] == "over" else "Under"

            # Real league-wide defense rank for this opponent/stat, same
            # lookup the console/Telegram report uses — falls back to a
            # plain opponent name if the rank lookup can't resolve.
            rank, total = edge_finder._defense_rank(
                edge_sport, p["stat"], p["opponent"], p["projection_direction"]
            )
            matchup_label = (
                f"#{rank}/{total} Defense vs {p['stat'].upper()}" if rank
                else f"vs {p['opponent']}"
            )
            # Same cap as edge_finder.py's format_edge_finder_report() —
            # this tab builds its own HTML straight from get_edge_finder()'s
            # raw dict, so it never picked up that cap. Uncapped, a
            # low-line prop (e.g. HITS Over 0.5) shows a misleading
            # 150%+ "edge" from a small denominator, not real signal.
            capped_edge_pct = max(
                -edge_finder.MAX_EDGE_PCT_FOR_SCORING,
                min(edge_finder.MAX_EDGE_PCT_FOR_SCORING, p["projection_edge_pct"]),
            )

            st.markdown(f"""
<div class="cp-overall" style="border-left-color:{conf_color};">
<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;">
<div>
<div class="label">#{i} &middot; {p['team_name']} vs {p['opponent']}</div>
<div class="value" style="font-size:20px;">{p['player_name']} &middot; {p['stat'].upper()} {direction_label} {p['line']}</div>
</div>
<div style="text-align:right;">
<div class="label">Edge Score</div>
<div style="color:{conf_color};font-size:26px;font-weight:800;">{p['edge_score']}</div>
<div style="color:{conf_color};font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;margin-top:2px;">{p['confidence']}</div>
</div>
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:14px;margin-top:16px;padding-top:14px;border-top:1px solid rgba(212,175,55,0.14);">
<div><div class="label">Hit Rate</div><div style="color:#fff;font-weight:700;">{p['hit_rate_overall']}% ({p['games_overall']}G)</div></div>
<div><div class="label">Projection Edge</div><div style="color:#fff;font-weight:700;">{abs(capped_edge_pct):.1f}%</div></div>
<div><div class="label">Matchup</div><div style="color:#fff;font-weight:700;">{matchup_label}</div></div>
</div>
</div>
""", unsafe_allow_html=True)

        st.caption(
            "Edge Score = 40% hit rate + 40% projection edge + 20% defense matchup, "
            "normalized against today's slate. HIGH confidence requires score >=80 and 15+ games."
        )

# =========================================================
# TAB 3: POWER RANKINGS
# =========================================================
# =========================================================
# TAB: PLAYER PROFILES
# =========================================================
with tab_players:
    st.markdown(
        '<div style="color:#8a7d55;font-size:12px;margin-bottom:14px;font-family:\'Oswald\',sans-serif;'
        'letter-spacing:1.5px;text-transform:uppercase;">Recent form, current props, and game log by player</div>',
        unsafe_allow_html=True,
    )

    pc1, pc2 = st.columns([1, 2])
    with pc1:
        profile_sport = st.selectbox("Sport", options=["wnba", "mlb", "nba", "nfl"], index=0, key="pp_sport")
    with pc2:
        player_options = load_player_list(profile_sport)
        if player_options:
            profile_player = st.selectbox(
                "Player",
                options=[""] + player_options,
                format_func=lambda x: x if x else "Select a player...",
                key="pp_player_select",
            )
        else:
            profile_player = ""
            st.caption(f"No players with recent data found for {profile_sport.upper()} yet.")

    with st.expander("Can't find them? Search by name instead"):
        manual_player = st.text_input("Player name", "", placeholder="e.g. Caitlin Clark", key="pp_player_manual")
        if manual_player:
            profile_player = manual_player

    if not profile_player:
        st.info("Pick a player above, or search by name, to pull their profile.")
    else:
        try:
            profile = player_profile.get_player_profile(profile_player, profile_sport, n_games=10)
        except Exception as e:
            st.error("player_profile.get_player_profile failed")
            st.exception(e)
            profile = None

        if profile:
            bio = profile["bio"]
            header_sub = (
                f"{bio.get('position', '?')} &middot; {bio.get('team_name', '?')} &middot; "
                f"{bio.get('height', '')} {bio.get('weight', '')}"
                if bio else "No bio on file for this sport yet"
            )
            st.markdown(f"""
<div class="cp-overall">
<div class="label">{profile['sport'].upper()}</div>
<div class="value" style="font-size:24px;">{profile['player_name']}</div>
<div style="color:#8a7d55;font-size:13px;margin-top:4px;">{header_sub}</div>
</div>
""", unsafe_allow_html=True)

            st.markdown(
                f'<div style="color:#fff;background:linear-gradient(180deg,rgba(24,22,12,0.65),rgba(12,11,6,0.75));'
                f'border:1px solid rgba(212,175,55,0.14);border-radius:14px;padding:16px 19px;margin-bottom:18px;">'
                f'{profile["notes"]}</div>',
                unsafe_allow_html=True,
            )

            if profile["current_props"]:
                st.markdown("**Current Props**")
                props_display = pd.DataFrame(profile["current_props"])[
                    ["stat", "line", "hit_rate_overall", "games_overall", "confidence_tier", "date"]
                ]
                props_display.columns = ["Stat", "Line", "Hit Rate %", "Games", "Tier", "As Of"]
                st.dataframe(props_display, hide_index=True, width="stretch")
            else:
                st.caption("No current props on file for this player.")

            if profile["game_log"]:
                st.markdown("**Recent Game Log**")
                stat_options = list(profile["game_log"].keys())
                chart_stat = st.selectbox("Stat", options=stat_options, key="pp_chart_stat")
                values = profile["game_log"].get(chart_stat, [])
                if values:
                    chart_df = pd.DataFrame({"Game": list(range(1, len(values) + 1)), chart_stat.upper(): values})
                    st.line_chart(chart_df.set_index("Game"))
            else:
                st.caption("No recent game log found for this player/sport.")

with tab_rankings:
    AVAILABLE_SPORTS = ["wnba", "nba", "nfl", "mlb"]
    rank_sport = st.selectbox("Sport", AVAILABLE_SPORTS, key="rank_sport")

    rankings = load_rankings(rank_sport)

    if not rankings:
        st.info(f"No power rankings available for {rank_sport.upper()} yet — "
                f"needs teams with enough graded games (min 3) and Elo history.")
    else:
        rank_rows = []
        for r in rankings:
            c = r["components"]
            raw = r["raw"]
            small_sample = raw["elo_games_played"] < 10
            rank_rows.append({
                "Rank": r["rank"],
                "Team": r["team"],
                "Power Score": r["power_score"],
                "Elo": c["elo_quality"],
                "Form": c["form"],
                "SOS": c["sos"],
                "Efficiency": c["efficiency"],
                "Efficiency Data": "Real" if c["efficiency_is_real_data"] else "Neutral (no data yet)",
                "Games": raw["elo_games_played"],
                "Small Sample": "⚠️" if small_sample else "",
            })

        rank_df = pd.DataFrame(rank_rows)
        st.write(f"**{len(rank_df)} teams ranked**")
        st.dataframe(
            rank_df, width="stretch", hide_index=True,
            column_config={
                "Power Score": st.column_config.NumberColumn(format="%.1f"),
                "Elo": st.column_config.NumberColumn(format="%.1f"),
                "Form": st.column_config.NumberColumn(format="%.1f"),
                "SOS": st.column_config.NumberColumn(format="%.1f"),
                "Efficiency": st.column_config.NumberColumn(format="%.1f"),
            },
        )
        st.caption("Power Score = 40% Elo (reliability-adjusted) + 25% Recent Form + "
                    "20% Efficiency + 15% Strength of Schedule. Betting-model activity "
                    "does not affect ranking. ⚠️ = fewer than 10 games played, rating "
                    "still stabilizing.")


# =========================================================
# TAB 4: BETTING ANALYTICS
# =========================================================
with tab_betting:
    period_label = st.radio("Period", ["Today", "Last 7 Days", "Season"], horizontal=True, key="perf_period")
    period_key = {"Today": "today", "Last 7 Days": "week", "Season": "season"}[period_label]

    summary = load_performance_summary(period_key)

    if not summary or summary["record"]["total"] == 0:
        st.info("No graded picks in this period.")
    else:
        r = summary["record"]
        roi = summary["roi"]

        st.markdown(
            f'<div class="cp-overall"><div class="label">Record — {period_label}</div>'
            f'<div class="value">{r["wins"]}-{r["losses"]} '
            f'<span class="pct">· {r["win_rate"]}%</span></div></div>',
            unsafe_allow_html=True,
        )

        if roi["roi_pct"] is not None:
            sign = "+" if roi["profit_units"] >= 0 else ""
            roi_color = "#3ecf8e" if roi["profit_units"] >= 0 else "#ff5c5c"
            cols = st.columns(3)
            with cols[0]:
                st.markdown(
                    f'<div class="cp-card"><div class="sport-name">Profit (units)</div>'
                    f'<div class="record" style="color:{roi_color};">{sign}{roi["profit_units"]}</div></div>',
                    unsafe_allow_html=True,
                )
            with cols[1]:
                st.markdown(
                    f'<div class="cp-card"><div class="sport-name">ROI</div>'
                    f'<div class="record" style="color:{roi_color};">{sign}{roi["roi_pct"]}%</div></div>',
                    unsafe_allow_html=True,
                )
            with cols[2]:
                st.markdown(
                    f'<div class="cp-card"><div class="sport-name">Picks w/ Odds</div>'
                    f'<div class="record">{roi["picks_used"]}</div></div>',
                    unsafe_allow_html=True,
                )
            if roi["picks_skipped_no_odds"]:
                st.caption(f"{roi['picks_skipped_no_odds']} graded pick(s) skipped — no odds on record.")
        else:
            st.caption("No picks with recorded odds this period — ROI unavailable.")

        if summary["by_sport"]:
            st.markdown("### By Sport")
            by_sport_df = pd.DataFrame(summary["by_sport"])
            by_sport_df.columns = ["Sport", "Total", "Wins", "Losses", "Win %"]
            by_sport_df["Sport"] = by_sport_df["Sport"].str.upper()
            st.dataframe(by_sport_df, width="stretch", hide_index=True)

        if summary["confidence_buckets"]:
            st.markdown("### Model Calibration")
            st.caption("Does the model's stated confidence match its actual win rate?")
            bucket_df = pd.DataFrame(summary["confidence_buckets"])
            bucket_df.columns = ["Confidence", "Total", "Wins", "Losses", "Actual Win Rate"]
            st.dataframe(bucket_df, width="stretch", hide_index=True)

        hl_cols = st.columns(2)
        if summary["best_pick"]:
            b = summary["best_pick"]
            with hl_cols[0]:
                st.markdown(f"""
<div class="cp-card" style="border-left:3px solid #3ecf8e;">
<div class="sport-name">Best pick &middot; {b['sport'].upper()}</div>
<div style="color:#fff;font-weight:700;font-size:15px;margin-top:4px;">{b['game']}</div>
<div style="color:#3ecf8e;font-weight:800;font-size:14px;margin-top:8px;">+{b['edge_at_pick']}% edge &middot; WIN</div>
</div>
""", unsafe_allow_html=True)
        if summary["worst_pick"]:
            w = summary["worst_pick"]
            with hl_cols[1]:
                st.markdown(f"""
<div class="cp-card" style="border-left:3px solid #ff5c5c;">
<div class="sport-name">Worst pick &middot; {w['sport'].upper()}</div>
<div style="color:#fff;font-weight:700;font-size:15px;margin-top:4px;">{w['game']}</div>
<div style="color:#ff5c5c;font-weight:800;font-size:14px;margin-top:8px;">+{w['edge_at_pick']}% edge &middot; LOSS</div>
</div>
""", unsafe_allow_html=True)
