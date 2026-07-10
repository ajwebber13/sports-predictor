"""
Culture & Pulse Picks — Tracking Dashboard
Pulls game picks + player props from Turso (cp-analytics DB).

SETUP:
1. pip install streamlit libsql-experimental pandas
2. Set env vars: TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, DASHBOARD_PASSWORD
3. Deploy on Render (libsql-experimental has no Windows wheel — Linux only)

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
"""

import os
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import libsql_experimental as libsql

st.set_page_config(page_title="Culture & Pulse Picks", layout="wide", initial_sidebar_state="collapsed")

# ---------- PASSWORD GATE ----------
# Set DASHBOARD_PASSWORD in Render's env vars. Anyone with the URL otherwise
# sees your model's edge %, picks, and full performance — lock it before
# sharing this link with anyone outside yourself.
def check_password():
    def password_entered():
        if st.session_state.get("pw_input") == os.environ.get("DASHBOARD_PASSWORD", ""):
            st.session_state["authenticated"] = True
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
    return False

if not os.environ.get("DASHBOARD_PASSWORD"):
    st.warning("DASHBOARD_PASSWORD not set — dashboard is unprotected. Add it in Render's environment variables.")
elif not check_password():
    st.stop()

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
TEAM_ID_MAPS = {"mlb": MLB_TEAM_IDS, "wnba": WNBA_TEAM_IDS}

def team_logo_url(sport: str, team_name: str) -> str:
    ids = TEAM_ID_MAPS.get((sport or "").lower(), {})
    team_id = ids.get(team_name)
    if not team_id:
        return ""
    return f"https://a.espncdn.com/i/teamlogos/{sport.lower()}/500/{team_id}.png"

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

# ---------- SPARKLINE PROPS TABLE (custom HTML/JS component) ----------
# Streamlit's native st.dataframe renders to canvas internally, so it can't
# show an inline recent-form sparkline per row — the thing that makes
# Outlier/Bobby's Bets props tables actually useful at a glance. This
# builds a real HTML table instead, with server-rendered SVG sparklines
# (last 5 games vs the line, colored by hit/miss) and a small vanilla-JS
# click-to-sort so we don't lose the sortability of the native table.

GAME_LOG_TABLES = {"wnba": "wnba_game_log", "mlb": "mlb_game_log", "nba": "nba_game_log"}
STAT_COLS = {
    "wnba": {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
             "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")},
    "nba":  {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk",
             "pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")},
    "mlb":  {"hits": "hits", "runs": "runs", "rbis": "rbis", "hr": "hrs"},
}

@st.cache_data(ttl=300)
def get_recent_values(sport: str, player_name: str, stat: str, n: int = 5) -> list:
    """Last n games' actual value for this stat, oldest to newest (left to
    right on the sparkline). Returns [] for sports/stats without a game log
    yet (e.g. CFB/NFL) instead of crashing — same graceful-degrade pattern
    used everywhere else in this build."""
    table = GAME_LOG_TABLES.get(sport)
    if not table:
        return []
    col_def = STAT_COLS.get(sport, {}).get(stat)
    if col_def is None:
        return []
    select_expr = " + ".join(col_def) if isinstance(col_def, tuple) else col_def
    try:
        conn = get_connection()
        cur = conn.execute(
            f"SELECT {select_expr} as val FROM {table} WHERE player_name = ? ORDER BY date DESC LIMIT ?",
            (player_name, n),
        )
        rows = cur.fetchall()
    except Exception:
        return []
    values = [r[0] for r in rows if r[0] is not None]
    values.reverse()
    return values


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
        result_color = {"HIT": "#3ecf8e", "MISS": "#ff5c5c", "PENDING": "#6b6b6b"}.get(r.get("status"), "#6b6b6b")
        body_rows.append(f"""
<tr>
  <td data-val="{esc(r['player'])}">{team_logo_html}<b style="color:#fff;">{esc(r['player'])}</b><div style="color:#6b6b6b;font-size:11px;margin-left:{'30px' if team_logo_html else '0'};">{esc(r['team'])}</div></td>
  <td data-val="{esc(r['opponent'])}">{opp_logo_html}{esc(r['opponent'])}</td>
  <td data-val="{esc(r['sport'])}">{esc(r['sport']).upper()}</td>
  <td data-val="{esc(r['stat'])}">{esc(r['stat']).upper()} {r['line']}</td>
  <td data-val="{esc(r['play'])}">{r['play']}</td>
  <td data-val="{r.get('edge_pct') or 0}">{r['sparkline_svg']}</td>
  <td data-val="{r.get('projected') or 0}">{r['projected'] if r.get('projected') is not None else '—'}</td>
  <td data-val="{r.get('edge_pct') or 0}" style="color:{'#3ecf8e' if (r.get('edge_pct') or 0) >= 0 else '#ff5c5c'};font-weight:700;">{f"{r['edge_pct']:+.1f}%" if r.get('edge_pct') is not None else '—'}</td>
  <td data-val="{r.get('hit_rate') or 0}">{f"{r['hit_rate']:.0f}%" if r.get('hit_rate') is not None else '—'}</td>
  <td data-val="{r.get('matchup') or 0}">{f"{r['matchup']:.2f}" if r.get('matchup') is not None else '—'}</td>
  <td data-val="{esc(r['odds'])}">{esc(r['odds'])}</td>
  <td data-val="{esc(r['status'])}" style="color:{result_color};font-weight:700;">{esc(r['status'])}</td>
</tr>""")

    headers = [
        ("Player", "text", False), ("Opp", "text", False), ("Sport", "text", False),
        ("Stat / Line", "text", False), ("Play", "text", False), ("Last 5", "num", True),
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
    border: 1px solid rgba(212,175,55,0.14); border-radius: 16px; overflow: hidden;
    box-shadow: 0 12px 32px rgba(0,0,0,0.45);
  }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  thead th {{
    background: rgba(19,18,9,0.9); color:#a8905c; font-family:'Oswald',sans-serif; font-weight:600;
    font-size:11px; letter-spacing:1px; text-transform:uppercase; text-align:left;
    padding:12px 14px; border-bottom:1px solid rgba(212,175,55,0.14); position:sticky; top:0;
    transition: color 0.15s ease;
  }}
  thead th:hover {{ color:#D4AF37; }}
  tbody td {{ padding:10px 14px; border-bottom:1px solid rgba(212,175,55,0.06); color:#c9c2ae; white-space:nowrap; }}
  tbody tr {{ transition: background 0.15s ease; }}
  tbody tr:hover {{ background: rgba(212,175,55,0.05); }}
</style></head>
<body>
<div class="cp-glass-wrap">
<table id="cpPropsTable">
  <thead><tr>{header_html}</tr></thead>
  <tbody>{"".join(body_rows)}</tbody>
</table>
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
# Brand: near-black #0A0A0A background with a subtle ambient radial glow,
# gold #D4AF37 primary accent, ticker gold #feb400, Bebas Neue for headlines,
# Oswald for labels, DM Sans for body. Cards use frosted-glass panels
# (translucent fill + backdrop blur + soft shadow) instead of flat fills,
# with a hairline gold-gradient top edge and a smooth hover lift — the
# "premium terminal" feel from Outlier/Bobby's Bets rather than a flat
# internal dashboard. Win/loss keeps green/red since that's the clearest
# convention for that specific signal.
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

/* ---- header ---- */
.cp-header { display: flex; align-items: center; justify-content: space-between; padding: 4px 0 22px 0; margin-bottom: 10px; border-bottom: 1px solid rgba(212,175,55,0.14); position: relative; }
.cp-header::after { content: ""; position: absolute; bottom: -1px; left: 0; width: 140px; height: 1px; background: linear-gradient(90deg, #D4AF37, transparent); }
.cp-header .brand { display: flex; align-items: center; gap: 10px; }
.cp-header .dot { width: 9px; height: 9px; border-radius: 50%; background: #feb400; box-shadow: 0 0 10px #feb400, 0 0 20px rgba(254,180,0,0.4); animation: cp-pulse 2s ease-in-out infinite; }
@keyframes cp-pulse { 0%, 100% { opacity: 1; box-shadow: 0 0 10px #feb400, 0 0 20px rgba(254,180,0,0.4); } 50% { opacity: 0.55; box-shadow: 0 0 4px #feb400; } }
.cp-header h1 { font-family: 'Bebas Neue', sans-serif; font-size: 36px; font-weight: 400; color: #ffffff; margin: 0; letter-spacing: 1.5px; }
.cp-header .sub { font-family: 'Oswald', sans-serif; color: #8a7d55; font-size: 11px; font-weight: 500; letter-spacing: 1.5px; text-transform: uppercase; }

/* ---- glass card base, reused everywhere ---- */
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

/* ---- headline metric banner (glass, gradient edge, gold-glow number) ---- */
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

/* labels above filter widgets (Sport, Result, Min Edge, Search...) — match the
   Oswald/gold-muted label style used everywhere else instead of Streamlit default */
.stMultiSelect label p, .stSlider label p, .stTextInput label p, .stDateInput label p {
    font-family: 'Oswald', sans-serif !important; color: #8a7d55 !important; font-size: 11px !important;
    font-weight: 600 !important; letter-spacing: 1.5px !important; text-transform: uppercase;
}

/* ---- data table + filter inputs, glass-matched ---- */
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

/* ---- tabs styled as pill-shaped glass toggles ---- */
.stTabs [data-baseweb="tab-list"] { gap: 6px; }
.stTabs [data-baseweb="tab"] {
    background-color: rgba(19,18,9,0.55); backdrop-filter: blur(10px);
    border: 1px solid rgba(212,175,55,0.12); border-radius: 10px 10px 0 0;
    color: #8a7d55; font-family: 'Oswald', sans-serif; padding: 9px 20px;
    transition: color 0.18s ease, background 0.18s ease;
}
.stTabs [data-baseweb="tab"]:hover { color: #D4AF37; background-color: rgba(212,175,55,0.06); }
.stTabs [aria-selected="true"] { color: #D4AF37 !important; border-bottom: 2px solid #D4AF37 !important; background-color: rgba(212,175,55,0.08) !important; }

/* tighten default Streamlit block spacing for a denser, more data-tool feel */
div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column"] { gap: 0.5rem; }
.block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)


# ---------- CONNECT TO TURSO ----------
@st.cache_resource
def get_connection():
    url = os.environ["TURSO_DATABASE_URL"]
    token = os.environ["TURSO_AUTH_TOKEN"]
    return libsql.connect("local.db", sync_url=url, auth_token=token)

@st.cache_data(ttl=300)
def load_picks():
    conn = get_connection()
    conn.sync()
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
def load_props():
    conn = get_connection()
    conn.sync()

    # The projection columns (opponent_team, projected_stat, etc.) only get
    # added to player_props the first time fetch_prizepicks_props.py
    # actually saves a projection — on a freshly wiped table, or before
    # that first run, they may not exist yet. Check what's really there
    # instead of assuming, so this doesn't crash on a fresh deploy.
    existing_cols = set()
    try:
        cur = conn.execute("PRAGMA table_info(player_props)")
        existing_cols = {row[1] for row in cur.fetchall()}
    except Exception:
        pass

    has_opponent_team = "opponent_team" in existing_cols
    projection_cols = ["projected_stat", "projection_edge", "projection_edge_pct",
                        "projection_direction", "projection_tier", "defense_factor"]
    available_proj_cols = [c for c in projection_cols if c in existing_cols]

    opponent_expr = "COALESCE(pp.opponent_team, pp.opponent)" if has_opponent_team else "pp.opponent"
    proj_select = ", ".join(f"pp.{c}" for c in available_proj_cols)
    proj_select_bare = ", ".join(available_proj_cols)

    cols = (["date", "sport", "player_name", "team_name", "opponent", "stat", "line",
             "over_odds", "under_odds", "hit_rate_overall", "confidence_tier"]
            + available_proj_cols
            + ["actual_value", "hit", "team_won"])

    query_with_results = f"""
        SELECT pp.date, pp.sport, pp.player_name, pp.team_name,
               {opponent_expr} as opponent,
               pp.stat, pp.line, pp.over_odds, pp.under_odds,
               pp.hit_rate_overall, pp.confidence_tier
               {"," + proj_select if proj_select else ""},
               pr.actual_value, pr.hit, pr.team_won
        FROM player_props pp
        LEFT JOIN prop_results pr
          ON pr.date = pp.date AND pr.player_name = pp.player_name AND pr.stat = pp.stat
        ORDER BY pp.date DESC
    """
    # prop_results only gets created once prop_tracker.py runs for the first
    # time — until then, fall back to player_props alone so props still show
    # as PENDING instead of crashing the whole dashboard.
    try:
        cur = conn.execute(query_with_results)
        rows = cur.fetchall()
        return pd.DataFrame(rows, columns=cols)
    except Exception:
        base_cols = ["date", "sport", "player_name", "team_name", "opponent", "stat", "line",
                     "over_odds", "under_odds", "hit_rate_overall", "confidence_tier"] + available_proj_cols
        query_no_results = f"""
            SELECT date, sport, player_name, team_name,
                   {opponent_expr.replace("pp.", "")} as opponent,
                   stat, line, over_odds, under_odds, hit_rate_overall, confidence_tier
                   {"," + proj_select_bare if proj_select_bare else ""}
            FROM player_props
            ORDER BY date DESC
        """
        cur = conn.execute(query_no_results)
        rows = cur.fetchall()
        df = pd.DataFrame(rows, columns=base_cols)
        df["actual_value"] = None
        df["hit"] = None
        df["team_won"] = None
        # ensure every column the rest of the app expects is present, even
        # if this deploy's table doesn't have the projection columns yet
        for c in projection_cols:
            if c not in df.columns:
                df[c] = None
        return df


# ---------- HEADER ----------
st.markdown(
    '<div class="cp-header"><div class="brand"><div class="dot"></div>'
    '<div><h1>Culture & Pulse Picks</h1>'
    '<div class="sub">Live model performance tracking</div></div></div></div>',
    unsafe_allow_html=True,
)

tab_games, tab_props = st.tabs(["Game Picks", "Player Props"])

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
            use_container_width=True, hide_index=True,
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
    props_df = load_props()

    if props_df.empty:
        st.info("No player props logged yet.")
    else:
        props_df["hit"] = pd.to_numeric(props_df["hit"], errors="coerce")
        props_df["actual_value"] = pd.to_numeric(props_df["actual_value"], errors="coerce")
        props_df["hit_rate_overall"] = pd.to_numeric(props_df["hit_rate_overall"], errors="coerce")
        props_df["projected_stat"] = pd.to_numeric(props_df["projected_stat"], errors="coerce")
        props_df["projection_edge_pct"] = pd.to_numeric(props_df["projection_edge_pct"], errors="coerce")
        props_df["defense_factor"] = pd.to_numeric(props_df["defense_factor"], errors="coerce")

        def prop_status(row):
            if pd.isna(row["hit"]):
                return "PENDING"
            return "HIT" if row["hit"] == 1 else "MISS"
        props_df["status"] = props_df.apply(prop_status, axis=1)

        settled_props = props_df[props_df["status"].isin(["HIT", "MISS"])]
        if not settled_props.empty:
            hits = int((settled_props["status"] == "HIT").sum())
            total = len(settled_props)
            hit_pct = round(hits / total * 100, 1) if total else 0
            st.markdown(
                f'<div class="cp-overall"><div class="label">Props Record</div>'
                f'<div class="value">{hits}-{total - hits} <span class="pct">· {hit_pct}%</span></div></div>',
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
            status_f = st.multiselect("Result", options=["HIT", "MISS", "PENDING"], default=["HIT", "MISS", "PENDING"], key="p_status")
        with fc3:
            min_edge = st.slider("Min Edge %", 0.0, 50.0, 0.0, 1.0, key="p_edge")
        with fc4:
            search = st.text_input("Search player", "", key="p_search")

        pf = props_df[
            props_df["sport"].isin(sport_f)
            & props_df["status"].isin(status_f)
        ].copy()
        if "projection_edge_pct" in pf.columns:
            pf = pf[(pf["projection_edge_pct"].abs() >= min_edge) | pf["projection_edge_pct"].isna()]
        if search:
            pf = pf[pf["player_name"].str.contains(search, case=False, na=False)]

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

            display = display.sort_values(
                "projection_edge_pct", key=lambda s: s.abs(), ascending=False, na_position="last"
            )

            table_rows = []
            for _, row in display.iterrows():
                recent = get_recent_values(row["sport"], row["player_name"], row["stat"], n=5)
                direction = row.get("projection_direction") or "over"
                spark = sparkline_svg(recent, row["line"], direction=direction)
                table_rows.append({
                    "player": row["player_name"], "team": row["team_name"], "team_logo": row["team_logo"],
                    "opponent": row["opponent"], "opp_logo": row["opp_logo"],
                    "sport": row["sport"], "stat": row["stat"], "line": row["line"],
                    "play": row["Play"], "sparkline_svg": spark,
                    "projected": row["projected_stat"] if pd.notna(row.get("projected_stat")) else None,
                    "edge_pct": row["projection_edge_pct"] if pd.notna(row.get("projection_edge_pct")) else None,
                    "hit_rate": row["hit_rate_overall"] if pd.notna(row.get("hit_rate_overall")) else None,
                    "matchup": row["defense_factor"] if pd.notna(row.get("defense_factor")) else None,
                    "odds": row["Odds"], "status": row["status"],
                })

            table_height = min(72 + len(table_rows) * 42, 900)
            components.html(build_props_html(table_rows), height=table_height, scrolling=True)
            st.caption("Last 5: green dot = beat the line that game, red = missed · dashed line = the prop line · Matchup: >1.0 means that opponent allows more than league average for this stat, <1.0 means tougher than average")