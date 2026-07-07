"""
Culture & Pulse Picks — Tracking Dashboard
Pulls picks + results from Turso (cp-analytics DB) and shows record, win%, and pick detail.

SETUP:
1. pip install streamlit libsql-experimental pandas plotly
2. Set env vars: TURSO_DATABASE_URL, TURSO_AUTH_TOKEN
3. Run locally: streamlit run dashboard.py
4. Deploy on Render as a second web service (same repo, different start command)
5. Add the Render URL to your phone home screen for an app-like feel

Schema (confirmed from cp-analytics):
- predictions: id, date, sport, game, home_team, away_team, bet, odds,
  model_prob, implied_prob, edge, home_record, away_record, home_rest,
  away_rest, home_injuries, away_injuries, game_type, predicted_winner, created_at
- results: id, date, sport, game, home_team, away_team, home_score, away_score,
  actual_winner, prediction_id (FK -> predictions.id), correct (1/0/NULL),
  edge_at_pick, odds_at_pick, updated_at
"""

import os
import streamlit as st
import pandas as pd
import libsql_experimental as libsql
import plotly.express as px

st.set_page_config(page_title="Culture & Pulse Picks", layout="wide")

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
            p.home_team,
            p.away_team,
            p.bet,
            p.odds,
            p.model_prob,
            p.implied_prob,
            p.edge,
            p.predicted_winner,
            r.home_score,
            r.away_score,
            r.actual_winner,
            r.correct
        FROM predictions p
        LEFT JOIN results r ON r.prediction_id = p.id
        ORDER BY p.date DESC
    """
    cur = conn.execute(query)
    rows = cur.fetchall()
    cols = [c[0] for c in cur.description]
    return pd.DataFrame(rows, columns=cols)

df = load_picks()

if df.empty:
    st.warning("No picks found. Check your Turso connection or table name.")
    st.stop()

# Build a plain-language status column: WIN / LOSS / PENDING
def status(row):
    if pd.isna(row["correct"]):
        return "PENDING"
    return "WIN" if row["correct"] == 1 else "LOSS"

df["status"] = df.apply(status, axis=1)
df["final_score"] = df.apply(
    lambda r: f"{r['home_team']} {r['home_score']} - {r['away_score']} {r['away_team']}"
    if pd.notna(r["home_score"]) else "",
    axis=1,
)

# ---------- TOP: RECORD BY SPORT ----------
st.title("🏆 Culture & Pulse Picks")

settled = df[df["status"].isin(["WIN", "LOSS"])]

summary = (
    settled.groupby("sport")["status"]
    .value_counts()
    .unstack(fill_value=0)
)
summary["total"] = summary.get("WIN", 0) + summary.get("LOSS", 0)
summary["win_pct"] = (summary.get("WIN", 0) / summary["total"] * 100).round(1)

if not summary.empty:
    cols = st.columns(len(summary))
    for i, (sport, row) in enumerate(summary.iterrows()):
        with cols[i]:
            st.metric(
                label=sport,
                value=f"{int(row.get('WIN', 0))}-{int(row.get('LOSS', 0))}",
                delta=f"{row['win_pct']}%",
            )

    overall_wins = summary.get("WIN", pd.Series(dtype=int)).sum()
    overall_losses = summary.get("LOSS", pd.Series(dtype=int)).sum()
    overall_total = overall_wins + overall_losses
    overall_pct = round(overall_wins / overall_total * 100, 1) if overall_total else 0

    st.markdown(f"### Overall: {overall_wins}-{overall_losses} ({overall_pct}%)")

    fig = px.bar(
        summary.reset_index(),
        x="sport",
        y="win_pct",
        title="Win % by Sport",
        text="win_pct",
    )
    fig.update_layout(yaxis_range=[0, 100])
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No settled picks yet — results will populate once games finish and auto_results.py runs.")

# ---------- MIDDLE: FILTERS ----------
st.markdown("---")
st.subheader("Filter Picks")

col1, col2 = st.columns(2)
with col1:
    sport_filter = st.multiselect("Sport", options=df["sport"].unique(), default=list(df["sport"].unique()))
with col2:
    status_filter = st.multiselect("Result", options=["WIN", "LOSS", "PENDING"], default=["WIN", "LOSS", "PENDING"])

filtered = df[df["sport"].isin(sport_filter) & df["status"].isin(status_filter)]

# ---------- BOTTOM: PICK TABLE ----------
st.markdown("---")
st.subheader("Pick Detail")

display_cols = [
    "date", "sport", "game", "bet", "odds",
    "edge", "final_score", "status",
]
st.dataframe(
    filtered[display_cols].sort_values("date", ascending=False),
    use_container_width=True,
    hide_index=True,
)