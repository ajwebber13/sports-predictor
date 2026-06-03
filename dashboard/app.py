import streamlit as st
import requests
import pandas as pd
from datetime import datetime

API_BASE = "https://sports-predictor-api-44a0.onrender.com"

st.set_page_config(page_title="Betting Model", page_icon="🏈", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0a0e1a; color: #e8eaf0; }
.edge-card { background: #0f1424; border: 1px solid #1e2540; border-radius: 8px; padding: 20px; margin-bottom: 12px; }
.edge-strong { border-left: 4px solid #00ff88; }
.edge-moderate { border-left: 4px solid #ffd700; }
.edge-slight { border-left: 4px solid #4a90e2; }
#MainMenu {visibility: hidden;} footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("⚙ Controls")
    sport = st.selectbox("Sport", ["ncaaf","nfl","nba","ncaab"])
    simulations = st.select_slider("Simulations", [1000,5000,10000,25000,50000], value=10000)
    edge_min = st.slider("Min Edge %", 1.0, 15.0, 3.0, 0.5)
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()
    try:
        requests.get(f"{API_BASE}/", timeout=2)
        st.success("● API Connected")
    except:
        st.error("● API Disconnected")
    st.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")

st.title("🏈 Betting Model Dashboard")
st.caption("Enhanced Prediction Engine · Monte Carlo · Live Odds")

try:
    r = requests.get(f"{API_BASE}/edges", params={"sport": sport, "simulations": simulations}, timeout=30)
    data = r.json()
    bets = data.get("best_bets", [])
    filtered = [b for b in bets if b.get("edge", 0) * 100 >= edge_min]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Games", data.get("count", len(bets)))
    c2.metric("Edges Found", len(filtered))
    c3.metric("Top Edge", f"{max((b.get('edge',0)*100 for b in filtered), default=0):.1f}%")
    c4.metric("Avg Edge", f"{sum(b.get('edge',0) for b in filtered)/max(len(filtered),1)*100:.1f}%")

    st.markdown("---")
    st.subheader("💰 Edge Board")

    if not filtered:
        st.info("No edges above threshold. Lower the minimum edge % in the sidebar.")
    else:
        for bet in filtered:
            edge_pct = bet.get("edge", 0) * 100
            css = "edge-strong" if edge_pct >= 8 else "edge-moderate" if edge_pct >= 5 else "edge-slight"
            label = "★★★ STRONG" if edge_pct >= 8 else "★★ MODERATE" if edge_pct >= 5 else "★ SLIGHT"
            st.markdown(f"""
            <div class="edge-card {css}">
                <b style="font-size:18px">{bet.get('game','')}</b> &nbsp;
                <span style="color:#888">{bet.get('bet','')} · Odds: {bet.get('odds','N/A')}</span>
                <span style="float:right; font-size:24px; color:#00ff88"><b>{edge_pct:.1f}%</b> <small style="font-size:12px">{label}</small></span><br><br>
                <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">Model: {bet.get('model_prob',0):.1f}%</span>
                <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">Market: {bet.get('implied_prob',0):.1f}%</span>
                <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">Cover: {bet.get('cover_prob','N/A')}%</span>
                <span style="background:#1e2540; padding:3px 8px; border-radius:4px; font-size:12px">Confidence: {bet.get('confidence','N/A')}</span>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("📊 Data Table")
    if filtered:
        df = pd.DataFrame(filtered)
        if "edge" in df.columns:
            df["edge"] = (df["edge"] * 100).round(2)
            df.rename(columns={"edge": "edge_%"}, inplace=True)
        st.dataframe(df, use_container_width=True, hide_index=True)

except requests.exceptions.ConnectionError:
    st.error("Cannot connect to FastAPI. Make sure it is running on port 8000.")
except Exception as e:
    st.error(f"Error: {e}")
