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
- predictions / results: game picks, joined on prediction_id (see earlier notes)
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
        return "A+", "#3ecf8e"
    if pct >= 60:
        return "A", "#3ecf8e"
    if pct >= 55:
        return "B", "#8fd694"
    if pct >= 52.4:
        return "C", "#D4AF37"
    if pct >= 48:
        return "D", "#ff9d4d"
    return "F", "#ff5c5c"

# ---------- SPARKLINE PROPS TABLE (custom HTML/JS component) ----------
# Streamlit's native st.dataframe renders to canvas internally, so it can't
# show an inline recent-form sparkline per row — the thing that makes
# Outlier/Bobby's Bets props tables actually useful at a glance. This
# builds a real HTML table instead, with server-rendered SVG sparklines
# (last 10 games vs the line, colored by hit/miss) and a small vanilla-JS
# click-to-sort so we don't lose the sortability of the native table.

GAME_LOG_TABLES = {"wnba": "wnba_game_log", "mlb": "mlb_game_log", "nba": "nba_game_log", "nfl": "nfl_game_log"}
STAT_COLS = {
    "wnba": {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
             "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")},
    "nba":  {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
             "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")},
    "mlb":  {"hits": "hits", "runs": "runs", "rbis": "rbis", "hr": "hrs"},
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
        color = "#3ecf8e" if beat else "#ff5c5c"
        dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2" fill="{color}" />')

    line_y = y_of(line_value)
    polyline = f'<polyline points="{" ".join(points)}" fill="none" stroke="#8a7d55" stroke-width="1.3" />'
    ref_line = (f'<line x1="{pad}" y1="{line_y:.1f}" x2="{width - pad}" y2="{line_y:.1f}" '
                f'stroke="#D4AF3766" stroke-width="1" stroke-dasharray="2,2" />')
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
  <td data-val="{r.get('edge_pct') or 0}" style="color:#D4AF37;font-weight:700;">{f"{abs(r['edge_pct']):.1f}%" if r.get('edge_pct') is not None else '—'}</td>
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
  @import url('https://fonts.googleapis.com/css2?family=Oswald:wght@500;600;700&family=DM+Sans:wght@400;500;700&display=swap');
  body {{ margin:0; background:transparent; font-family:'DM Sans',sans-serif; }}
  .cp-glass-wrap {{
    background: linear-gradient(180deg, rgba(19,18,9,0.75), rgba(10,10,10,0.9));
    backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
    border: 1px solid rgba(212,175,55,0.14); border-radius: 16px;
    box-shadow: 0 12px 32px rgba(0,0,0,0.45);
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
    overflow-x: auto; overflow-y: auto; max-height: 560px;
    -webkit-overflow-scrolling: touch; border-radius: 16px;
  }}
  table {{ width:100%; min-width:900px; border-collapse:collapse; font-size:13px; }}
  thead th {{
    background: rgba(19,18,9,0.98); color:#a8905c; font-family:'Oswald',sans-serif; font-weight:600;
    font-size:11px; letter-spacing:1px; text-transform:uppercase; text-align:left;
    padding:12px 14px; border-bottom:1px solid rgba(212,175,55,0.14); position:sticky; top:0; z-index:2;
    transition: color 0.15s ease;
  }}
  thead th:hover {{ color:#D4AF37; }}
  tbody td {{ padding:10px 14px; border-bottom:1px solid rgba(212,175,55,0.06); color:#c9c2ae; white-space:nowrap; }}
  tbody tr {{ transition: background 0.15s ease; }}
  tbody tr:hover {{ background: rgba(212,175,55,0.05); }}
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
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Oswald:wght@500;600;700&family=DM+Sans:wght@400;500;700&display=swap');

.stApp {
    background:
        radial-gradient(ellipse 900px 500px at 15% -10%, rgba(212,175,55,0.055), transparent 60%),
        radial-gradient(ellipse 700px 500px at 100% 0%, rgba(212,175,55,0.03), transparent 55%),
        #0A0A0A;
}
#MainMenu, footer, header { visibility: hidden; }
* { font-family: 'DM Sans', -apple-system, sans-serif; }

.cp-header { display: flex; align-items: center; justify-content: space-between; padding: 4px 0 22px 0; margin-bottom: 10px; border-bottom: 1px solid rgba(212,175,55,0.14); position: relative; }
.cp-header::after { content: ""; position: absolute; bottom: -1px; left: 0; width: 140px; height: 1px; background: linear-gradient(90deg, #D4AF37, transparent); }
.cp-header .brand { display: flex; align-items: center; gap: 10px; }
.cp-header .dot { width: 9px; height: 9px; border-radius: 50%; background: #feb400; box-shadow: 0 0 10px #feb400, 0 0 20px rgba(254,180,0,0.4); animation: cp-pulse 2s ease-in-out infinite; }
@keyframes cp-pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 10px #feb400, 0 0 20px rgba(254,180,0,0.4); } 50% { opacity: 0.55; box-shadow: 0 0 4px #feb400; } }
.cp-header h1 { font-family: 'Bebas Neue', sans-serif; font-size: 36px; font-weight: 400; color: #ffffff; margin: 0; letter-spacing: 1.5px; }
.cp-header .sub { font-family: 'Oswald', sans-serif; color: #8a7d55; font-size: 11px; font-weight: 500; letter-spacing: 1.5px; text-transform: uppercase; }

.cp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 14px; margin-bottom: 22px; }
.cp-card {
    background: linear-gradient(180deg, rgba(24,22,12,0.65), rgba(12,11,6,0.75));
    backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
    border: 1px solid rgba(212,175,55,0.14);
    border-radius: 14px; padding: 17px 19px; position: relative; overflow: hidden;
    box-shadow: 0 6px 20px rgba(0,0,0,0.35);
    transition: border-color 0.22s cubic-bezier(.2,.8,.2,1), transform 0.22s cubic-bezier(.2,.8,.2,1), box-shadow 0.22s cubic-bezier(.2,.8,.2,1);
}
.cp-card::before { content: ""; position: absolute; top: 0; left: 0; right: 0; height: 1px; background: linear-gradient(90deg, transparent, rgba(212,175,55,0.55), transparent); }
.cp-card:hover { border-color: rgba(212,175,55,0.4); transform: translateY(-2px); box-shadow: 0 10px 28px rgba(0,0,0,0.45), 0 0 0 1px rgba(212,175,55,0.08); }
.cp-card .sport-name { font-family: 'Oswald', sans-serif; color: #8a7d55; font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 8px; }
.cp-card .record { color: #ffffff; font-size: 27px; font-weight: 800; line-height: 1; letter-spacing: -0.5px; }
.cp-card .pct-row { display: flex; align-items: center; gap: 5px; margin-top: 9px; }
.cp-card .pct-up { color: #3ecf8e; font-size: 13px; font-weight: 700; }
.cp-card .pct-down { color: #ff5c5c; font-size: 13px; font-weight: 700; }

.cp-overall {
    background: linear-gradient(135deg, rgba(26,22,8,0.85), rgba(10,10,10,0.9));
    backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
    border: 1px solid rgba(212,175,55,0.22); border-left: 3px solid #D4AF37;
    border-radius: 14px; padding: 20px 24px; margin-bottom: 22px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.4);
}
.cp-overall .label { font-family: 'Oswald', sans-serif; color: #8a7d55; font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 5px; font-weight: 600; }
.cp-overall .value { color: #ffffff; font-size: 31px; font-weight: 800; letter-spacing: -0.5px; }
.cp-overall .value .pct { color: #D4AF37; text-shadow: 0 0 18px rgba(212,175,55,0.35); }

.tier-green { background: rgba(62,207,142,0.14); color: #3ecf8e; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; border: 1px solid rgba(62,207,142,0.25); }
.tier-yellow { background: rgba(232,197,71,0.14); color: #e8c547; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; border: 1px solid rgba(232,197,71,0.25); }

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
.stSlider [data-baseweb="slider"] > div > div { background: #D4AF37 !important; }
.stSlider [role="slider"] { background-color: #D4AF37 !important; border-color: #D4AF37 !important; box-shadow: 0 0 10px rgba(212,175,55,0.5) !important; }

hr { border-color: rgba(212,175,55,0.14) !important; margin: 22px 0 !important; }

.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    background-color: rgba(19,18,9,0.55); backdrop-filter: blur(10px);
    border: 1px solid rgba(212,175,55,0.12); border-radius: 10px 10px 0 0;
    color: #8a7d55; font-family: 'Oswald', sans-serif; padding: 9px 20px;
    transition: color 0.18s ease, background 0.18s ease;
}
.stTabs [data-baseweb="tab"]:hover { color: #D4AF37; background-color: rgba(212,175,55,0.06); }
.stTabs [aria-selected="true"] { color: #D4AF37 !important; border-bottom: 2px solid #D4AF37 !important; background-color: rgba(212,175,55,0.08) !important; }

div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column"] { gap: 0.5rem; }
.block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=300)
def load_picks():
    conn = get_conn()

    query = """
        SELECT p.date, p.sport, p.game, p.bet, p.odds, p.edge,
               p.model_prob, p.implied_prob, p.home_record, p.away_record,
               p.home_rest, p.away_rest, p.home_injuries, p.away_injuries,
               r.home_team, r.away_team, r.home_score, r.away_score, r.correct
        FROM predictions p
        LEFT JOIN results r ON r.prediction_id = p.id
        ORDER BY p.date DESC
    """
    cur = conn.execute(query)
    rows = cur.fetchall()
    cols = ["date", "sport", "game", "bet", "odds", "edge",
            "model_prob", "implied_prob", "home_record", "away_record",
            "home_rest", "away_rest", "home_injuries", "away_injuries",
            "result_home_team", "result_away_team", "home_score", "away_score", "correct"]
    return pd.DataFrame(rows, columns=cols)


@st.cache_data(ttl=300)
def load_rankings(sport: str):
    """Wraps ranking_engine.get_rankings() — pure compute, no stored
    table, so this just caches the live result for 5 minutes instead
    of recomputing on every rerun."""
    try:
        return ranking_engine.get_rankings(sport)
    except Exception:
        return []


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

        def status(row):
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

            st.markdown(
                f'<div class="cp-overall"><div class="label">Overall Record</div>'
                f'<div class="value">{overall_wins}-{overall_losses} <span class="pct">· {overall_pct}%</span></div></div>',
                unsafe_allow_html=True,
            )

            cards = ['<div class="cp-grid">']
            for sport, row in summary.iterrows():
                pct = row["win_pct"]
                pct_class = "pct-up" if pct >= 50 else "pct-down"
                streak = streaks.get(sport)
                if streak:
                    s_type, s_count = streak
                    s_color = "#3ecf8e" if s_type == "WIN" else "#ff5c5c"
                    s_letter = "W" if s_type == "WIN" else "L"
                    streak_html = f'<span style="color:{s_color};font-size:11px;font-weight:700;margin-left:8px;">{s_letter}{s_count} streak</span>'
                else:
                    streak_html = ""
                cards.append(
                    f'<div class="cp-card"><div class="sport-name">{sport}</div>'
                    f'<div class="record">{int(row.get("WIN", 0))}-{int(row.get("LOSS", 0))}</div>'
                    f'<div class="pct-row"><span class="{pct_class}">{pct}%</span>{streak_html}</div></div>'
                )
            cards.append('</div>')
            st.markdown(''.join(cards), unsafe_allow_html=True)

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
<div style="color:#fff;font-weight:700;font-size:15px;margin-top:4px;">{best['bet']}</div>
<div style="color:#8a7d55;font-size:12px;margin-top:4px;">{best['game']} &middot; {best['date']}</div>
<div style="color:#3ecf8e;font-weight:800;font-size:14px;margin-top:8px;">+{best['edge']}% edge &middot; WIN</div>
</div>
""", unsafe_allow_html=True)
            if worst is not None:
                with hl_cols[1]:
                    st.markdown(f"""
<div class="cp-card" style="border-left:3px solid #ff5c5c;">
<div class="sport-name">Worst pick &middot; {worst['sport']}</div>
<div style="color:#fff;font-weight:700;font-size:15px;margin-top:4px;">{worst['bet']}</div>
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
        fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1.5])
        with fc1:
            sport_filter = st.multiselect("Sport", options=df["sport"].unique(), default=list(df["sport"].unique()), key="g_sport")
        with fc2:
            status_filter = st.multiselect("Result", options=["WIN", "LOSS", "PENDING"], default=["WIN", "LOSS", "PENDING"], key="g_status")
        with fc3:
            min_edge_g = st.slider("Min Edge %", 0.0, 50.0, 0.0, 1.0, key="g_edge")
        with fc4:
            search_g = st.text_input("Search team/game", "", key="g_search")

        filtered = df[df["sport"].isin(sport_filter) & df["status"].isin(status_filter)].copy()
        filtered["edge"] = pd.to_numeric(filtered["edge"], errors="coerce")
        filtered = filtered[(filtered["edge"].abs() >= min_edge_g) | filtered["edge"].isna()]
        if search_g:
            filtered = filtered[filtered["game"].str.contains(search_g, case=False, na=False)
                                 | filtered["bet"].str.contains(search_g, case=False, na=False)]

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

        # Pull the team name being bet on out of the "bet" field (e.g. "Miami Marlins ML")
        # to look up its logo — matches the sport's team ID map when available.
        def pick_logo(row):
            team_guess = row["bet"].replace(" ML", "").strip()
            return team_logo_url(row["sport"], team_guess)
        filtered["pick_logo"] = filtered.apply(pick_logo, axis=1)

        sorted_full = filtered.sort_values("date", ascending=False).reset_index(drop=True)
        st.write(f"**{len(sorted_full)} picks**")
        display_cols = ["pick_logo", "date", "sport", "game", "bet", "Tier", "odds", "edge", "final_score", "status"]

        event = st.dataframe(
            sorted_full[display_cols],
            width="stretch", hide_index=True, height=600,
            column_config={
                "pick_logo": st.column_config.ImageColumn(""),
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
            model_prob = f"{g['model_prob']:.1f}%" if pd.notna(g["model_prob"]) else "—"
            implied_prob = f"{g['implied_prob']:.1f}%" if pd.notna(g["implied_prob"]) else "—"
            score_line = g["final_score"] if g["final_score"] else "Not yet played"
            status_color = {"WIN": "#3ecf8e", "LOSS": "#ff5c5c", "PENDING": "#8a7d55"}[g["status"]]

            detail_slot.markdown(f"""
<div class="cp-overall" style="border-left-color:{status_color};">
<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:16px;">
<div>
<div class="label">{g['date']} &middot; {g['sport'].upper()}</div>
<div class="value" style="font-size:20px;">{g['game']}</div>
<div style="color:#8a7d55;font-size:13px;margin-top:6px;">Pick: <span style="color:#fff;font-weight:700;">{g['bet']}</span> ({g['odds']})</div>
</div>
<div style="text-align:right;">
<div class="label">Result</div>
<div style="color:{status_color};font-size:20px;font-weight:800;">{g['status']}</div>
<div style="color:#8a7d55;font-size:12px;margin-top:4px;">{score_line}</div>
</div>
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px;margin-top:16px;padding-top:14px;border-top:1px solid rgba(212,175,55,0.14);">
<div><div class="label">Model prob</div><div style="color:#D4AF37;font-weight:700;">{model_prob}</div></div>
<div><div class="label">Market implied</div><div style="color:#fff;font-weight:700;">{implied_prob}</div></div>
<div><div class="label">Edge</div><div style="color:#fff;font-weight:700;">{g['edge']}%</div></div>
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
        min_edge = st.slider("Min Edge %", 0.0, 50.0, 0.0, 1.0, key="p_edge")
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
        st.caption("👉 Swipe left/right to see all columns")
        # FIXED 2026-07-20: iframe height now matches .cp-scroll-wrap's
        # own 560px max-height + header/padding room — the inner wrapper
        # is what scrolls now (that's what makes the sticky header work),
        # so the outer iframe just needs to be tall enough to show it
        # without ALSO needing to scroll itself (that would mean two
        # nested scrollbars, which is worse than the original bug).
        table_height = min(72 + len(table_rows) * 42, 600)
        components.html(
            build_props_html(table_rows),
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
<div><div class="label">Projection Edge</div><div style="color:#fff;font-weight:700;">{abs(p['projection_edge_pct']):.1f}%</div></div>
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
        profile_player = st.text_input("Player name", "", placeholder="e.g. Caitlin Clark", key="pp_player")

    if not profile_player:
        st.info("Enter a player name above to pull their profile.")
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
<div class="sport-name">Worst beat &middot; {w['sport'].upper()}</div>
<div style="color:#fff;font-weight:700;font-size:15px;margin-top:4px;">{w['game']}</div>
<div style="color:#ff5c5c;font-weight:800;font-size:14px;margin-top:8px;">+{w['edge_at_pick']}% edge &middot; LOSS</div>
</div>
""", unsafe_allow_html=True)
