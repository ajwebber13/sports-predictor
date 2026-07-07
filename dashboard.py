"""
Culture & Pulse Picks — Tracking Dashboard
Pulls picks + results from Turso (cp-analytics DB) and shows record, win%, and pick detail.

SETUP:
1. pip install streamlit libsql-experimental pandas plotly
2. Set env vars: TURSO_DATABASE_URL, TURSO_AUTH_TOKEN
3. Deploy on Render (libsql-experimental has no Windows wheel — Linux only)

Schema (confirmed from cp-analytics):
- predictions: id, date, sport, game, home_team, away_team, bet, odds,
  model_prob, implied_prob, edge, home_record, away_record, home_rest,
  away_rest, home_injuries, away_injuries, game_type, predicted_winner, created_at
- results: id, date, sport, game, home_team, away_team, home_score, away_score,
  actual_winner, prediction_id (FK -> predictions.id), correct (1/0/NULL),
  edge_at_pick, odds_at_pick, updated_at

NOTE: libsql-experimental's cursor.description is NOT reliable for column
names in joined queries (confirmed via database.py's own _Row wrapper,
which avoids trusting it). Column names below are assigned manually in
the exact order of the SELECT clause instead of trusting cur.description.
"""

import os
import streamlit as st
import pandas as pd
import libsql_experimental as libsql
import plotly.graph_objects as go

st.set_page_config(page_title="Culture & Pulse Picks", layout="wide", initial_sidebar_state="collapsed")

# ---------- STYLE: Outlier.bet-inspired — near-black, data-card grid, green/red signal color ----------
st.markdown("""
<style>
    .stApp { background-color: #020202; }
    #MainMenu, footer, header { visibility: hidden; }

    * { font-family: -apple-system, 'Inter', 'Segoe UI', sans-serif; }

    .cp-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 4px 0 20px 0;
        margin-bottom: 8px;
    }
    .cp-header .brand { display: flex; align-items: center; gap: 10px; }
    .cp-header .dot {
        width: 10px; height: 10px; border-radius: 50%;
        background: #3ecf8e;
        box-shadow: 0 0 8px #3ecf8e;
    }
    .cp-header h1 {
        font-size: 22px;
        font-weight: 700;
        color: #ffffff;
        margin: 0;
        letter-spacing: -0.3px;
    }
    .cp-header .sub {
        color: #6b6b6b;
        font-size: 12px;
        font-weight: 500;
    }

    .cp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }

    .cp-card {
        background: #0f0f10;
        border: 1px solid #1e1e1e;
        border-radius: 14px;
        padding: 16px 18px;
    }
    .cp-card .sport-name {
        color: #6b6b6b;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        margin-bottom: 8px;
    }
    .cp-card .record {
        color: #ffffff;
        font-size: 26px;
        font-weight: 800;
        line-height: 1;
        letter-spacing: -0.5px;
    }
    .cp-card .pct-row { display: flex; align-items: center; gap: 5px; margin-top: 8px; }
    .cp-card .pct-up { color: #3ecf8e; font-size: 13px; font-weight: 700; }
    .cp-card .pct-down { color: #ff5c5c; font-size: 13px; font-weight: 700; }
    .cp-card .arrow-up::before { content: "▲ "; font-size: 10px; }
    .cp-card .arrow-down::before { content: "▼ "; font-size: 10px; }

    .cp-overall {
        background: #0f0f10;
        border: 1px solid #1e1e1e;
        border-left: 3px solid #3ecf8e;
        border-radius: 12px;
        padding: 18px 22px;
        margin-bottom: 20px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .cp-overall .label {
        color: #6b6b6b;
        font-size: 11px;
        letter-spacing: 1.2px;
        text-transform: uppercase;
        margin-bottom: 4px;
        font-weight: 700;
    }
    .cp-overall .value {
        color: #ffffff;
        font-size: 28px;
        font-weight: 800;
        letter-spacing: -0.5px;
    }
    .cp-overall .value .pct { color: #3ecf8e; }

    h3 { color: #ffffff !important; font-weight: 700 !important; font-size: 15px !important;
         text-transform: uppercase; letter-spacing: 1px; color: #6b6b6b !important; }

    section[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid #1e1e1e; }
    .stMultiSelect [data-baseweb="tag"] { background-color: #1a2e24 !important; color: #3ecf8e !important; border: 1px solid #3ecf8e33 !important; }
    hr { border-color: #1e1e1e !important; }
</style>
""", unsafe_allow_html=True)


# ---------- CONNECT TO TURSO ----------
@st.cache_resource
def get_connection():
    url = os.environ["TURSO_DATABASE_URL"]
    token = os.environ["TURSO_AUTH_TOKEN"]
    return libsql.connect("local.db", sync_url=url, auth_token=token)

@st.cache_data(ttl=300)  # refresh every 5 min
def load_picks():
    conn = get_connection()
    conn.sync()
    query = """
        SELECT
            p.date,
            p.sport,
            p.game,
            p.bet,
            p.odds,
            p.edge,
            r.home_team,
            r.away_team,
            r.home_score,
            r.away_score,
            r.correct
        FROM predictions p
        LEFT JOIN results r ON r.prediction_id = p.id
        ORDER BY p.date DESC
    """
    cur = conn.execute(query)
    rows = cur.fetchall()
    # Don't trust cur.description column names from libsql_experimental in joins —
    # assign manually in the exact order of the SELECT clause above.
    cols = ["date", "sport", "game", "bet", "odds", "edge",
            "result_home_team", "result_away_team", "home_score", "away_score", "correct"]
    return pd.DataFrame(rows, columns=cols)

df = load_picks()

if df.empty:
    st.warning("No picks found. Check your Turso connection or table name.")
    st.stop()

# Force numeric types explicitly — raw tuples from libsql may arrive as strings
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
    home = row["result_home_team"] or ""
    away = row["result_away_team"] or ""
    return f"{away} {int(row['away_score'])} - {int(row['home_score'])} {home}"

df["final_score"] = df.apply(build_score, axis=1)

# ---------- HEADER ----------
st.markdown("""
<div class="cp-header">
    <div class="brand">
        <div class="dot"></div>
        <div>
            <h1>Culture & Pulse Picks</h1>
            <div class="sub">Live model performance tracking</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ---------- TOP: RECORD BY SPORT ----------
settled = df[df["status"].isin(["WIN", "LOSS"])]

summary = (
    settled.groupby("sport")["status"]
    .value_counts()
    .unstack(fill_value=0)
)

if not summary.empty:
    summary["total"] = summary.get("WIN", 0) + summary.get("LOSS", 0)
    summary["win_pct"] = (summary.get("WIN", 0) / summary["total"] * 100).round(1)

    overall_wins = int(summary.get("WIN", pd.Series(dtype=int)).sum())
    overall_losses = int(summary.get("LOSS", pd.Series(dtype=int)).sum())
    overall_total = overall_wins + overall_losses
    overall_pct = round(overall_wins / overall_total * 100, 1) if overall_total else 0

    st.markdown(f"""
    <div class="cp-overall">
        <div>
            <div class="label">Overall Record</div>
            <div class="value">{overall_wins}-{overall_losses} <span class="pct">· {overall_pct}%</span></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    card_html = '<div class="cp-grid">'
    for sport, row in summary.iterrows():
        pct = row["win_pct"]
        pct_class = "pct-up arrow-up" if pct >= 50 else "pct-down arrow-down"
        card_html += f"""
        <div class="cp-card">
            <div class="sport-name">{sport}</div>
            <div class="record">{int(row.get('WIN', 0))}-{int(row.get('LOSS', 0))}</div>
            <div class="pct-row"><span class="{pct_class}">{pct}%</span></div>
        </div>
        """
    card_html += "</div>"
    st.markdown(card_html, unsafe_allow_html=True)

    fig = go.Figure(go.Bar(
        x=summary.index,
        y=summary["win_pct"],
        marker_color=["#3ecf8e" if p >= 50 else "#ff5c5c" for p in summary["win_pct"]],
        text=summary["win_pct"],
        texttemplate="%{text}%",
        textposition="outside",
        textfont=dict(color="#ffffff"),
    ))
    fig.update_layout(
        title=None,
        plot_bgcolor="#020202",
        paper_bgcolor="#020202",
        font_color="#6b6b6b",
        yaxis=dict(range=[0, 115], gridcolor="#1e1e1e", zeroline=False),
        xaxis=dict(gridcolor="#1e1e1e"),
        height=280,
        margin=dict(t=20, b=20, l=10, r=10),
        bargap=0.4,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No settled picks yet — results populate once games finish and auto_results.py runs.")

# ---------- FILTERS ----------
st.markdown("---")
st.subheader("Filter Picks")

col1, col2 = st.columns(2)
with col1:
    sport_filter = st.multiselect("Sport", options=df["sport"].unique(), default=list(df["sport"].unique()))
with col2:
    status_filter = st.multiselect("Result", options=["WIN", "LOSS", "PENDING"], default=["WIN", "LOSS", "PENDING"])

filtered = df[df["sport"].isin(sport_filter) & df["status"].isin(status_filter)]

# ---------- PICK TABLE ----------
st.subheader("Pick Detail")

display_cols = ["date", "sport", "game", "bet", "odds", "edge", "final_score", "status"]
st.dataframe(
    filtered[display_cols].sort_values("date", ascending=False),
    use_container_width=True,
    hide_index=True,
    column_config={
        "status": st.column_config.TextColumn("Result"),
        "final_score": st.column_config.TextColumn("Score"),
        "edge": st.column_config.NumberColumn("Edge %", format="%.1f"),
    },
)
