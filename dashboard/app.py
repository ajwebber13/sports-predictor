import streamlit as st
import requests
import pandas as pd
from datetime import datetime

API_BASE = "https://sports-predictor-api-44a0.onrender.com"

st.set_page_config(page_title="Culture & Pulse Analytics", page_icon="🏈", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0a0e1a; color: #e8eaf0; }
.edge-card { background: #0f1424; border: 1px solid #1e2540; border-radius: 8px; padding: 20px; margin-bottom: 12px; }
.edge-strong { border-left: 4px solid #00ff88; }
.edge-moderate { border-left: 4px solid #ffd700; }
.edge-slight { border-left: 4px solid #4a90e2; }
.wnba-card { background: #0f1424; border: 1px solid #1e2540; border-radius: 8px; padding: 20px; margin-bottom: 12px; border-left: 4px solid #ff69b4; }
.nba-card { background: #0f1424; border: 1px solid #1e2540; border-radius: 8px; padding: 20px; margin-bottom: 12px; border-left: 4px solid #c9a84c; }
#MainMenu {visibility: hidden;} footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("⚙ Controls")
    page = st.radio("View", ["🏈 Football Edges", "🏀 WNBA Edges", "🏀 NBA Edges", "🏀 WNBA Props"])
    st.markdown("---")

    if page == "🏈 Football Edges":
        sport = st.selectbox("Sport", ["ncaaf", "nfl", "ncaab"])
        simulations = st.select_slider("Simulations", [1000, 5000, 10000, 25000, 50000], value=10000)
        edge_min = st.slider("Min Edge %", 1.0, 15.0, 3.0, 0.5)
    elif page in ["🏀 WNBA Edges", "🏀 NBA Edges"]:
        simulations = st.select_slider("Simulations", [1000, 5000, 10000, 25000, 50000], value=10000)
        edge_min = st.slider("Min Edge %", 1.0, 15.0, 3.0, 0.5)
    else:
        edge_min = st.slider("Min Prop Edge %", 1.0, 10.0, 2.0, 0.5)

    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()

    try:
        requests.get(f"{API_BASE}/", timeout=3)
        st.success("● API Connected")
    except:
        st.error("● API Disconnected")

    st.caption(f"Updated: {datetime.now().strftime('%H:%M:%S')}")


# ─── FOOTBALL EDGES ───────────────────────────────────────────

if page == "🏈 Football Edges":
    st.title("🏈 Betting Model Dashboard")
    st.caption("Enhanced Prediction Engine · Monte Carlo · Live Odds")

    try:
        r = requests.get(f"{API_BASE}/edges", params={"sport": sport, "simulations": simulations}, timeout=60)
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
            st.info("No edges above threshold.")
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

    except Exception as e:
        st.error(f"Error: {e}")


# ─── WNBA EDGES ───────────────────────────────────────────────

elif page == "🏀 WNBA Edges":
    st.title("🏀 WNBA Edge Board")
    st.caption("Live ESPN Stats · Possession Model · Real Rest & Travel Data")

    try:
        r = requests.get(f"{API_BASE}/wnba/edges",
                         params={"simulations": simulations, "min_edge": edge_min},
                         timeout=60)
        data = r.json()
        bets = data.get("best_bets", [])
        filtered = [b for b in bets if b.get("edge", 0) * 100 >= edge_min]

        c1, c2, c3 = st.columns(3)
        c1.metric("Games", data.get("count", len(bets)))
        c2.metric("Edges Found", len(filtered))
        c3.metric("Top Edge", f"{max((b.get('edge',0)*100 for b in filtered), default=0):.1f}%")

        st.markdown("---")
        st.subheader("💰 WNBA Edge Board")

        if not filtered:
            st.info("No WNBA edges above threshold right now.")
        else:
            for bet in filtered:
                edge_pct = bet.get("edge", 0) * 100
                projected = bet.get("projected", "N/A")
                home_record = bet.get("home_record", "N/A")
                away_record = bet.get("away_record", "N/A")
                home_rest = bet.get("home_rest", "N/A")
                away_rest = bet.get("away_rest", "N/A")
                parts = bet.get("game", "").split(" @ ")
                away_team = parts[0] if len(parts) == 2 else ""
                home_team = parts[1] if len(parts) == 2 else ""

                st.markdown(f"""
                <div class="wnba-card">
                    <b style="font-size:18px">{bet.get('game','')}</b>
                    <span style="float:right; font-size:24px; color:#ff69b4"><b>{edge_pct:.1f}%</b></span><br>
                    <span style="color:#888; font-size:13px">{bet.get('bet','')} · Projected: {projected}</span><br><br>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">Model: {bet.get('model_prob',0):.1f}%</span>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">Market: {bet.get('implied_prob',0):.1f}%</span>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">{home_team}: {home_record} | {home_rest}d rest</span>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; font-size:12px">{away_team}: {away_record} | {away_rest}d rest</span>
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

    except Exception as e:
        st.error(f"Error: {e}")


# ─── NBA EDGES ────────────────────────────────────────────────

elif page == "🏀 NBA Edges":
    st.title("🏀 NBA Edge Board")
    st.caption("Net Rating Model · Live DraftKings & FanDuel Lines · NBA Finals")

    try:
        r = requests.get(f"{API_BASE}/nba/edges",
                         params={"simulations": simulations, "min_edge": edge_min},
                         timeout=60)
        data = r.json()
        bets = data.get("best_bets", [])
        filtered = [b for b in bets if b.get("edge", 0) * 100 >= edge_min]

        c1, c2, c3 = st.columns(3)
        c1.metric("Games", data.get("count", len(bets)))
        c2.metric("Edges Found", len(filtered))
        c3.metric("Top Edge", f"{max((b.get('edge',0)*100 for b in filtered), default=0):.1f}%")

        st.markdown("---")
        st.subheader("💰 NBA Edge Board")

        if not filtered:
            st.info("No NBA edges above threshold right now.")
        else:
            for bet in filtered:
                edge_pct    = bet.get("edge", 0) * 100
                net_home    = bet.get("net_rating_home", "N/A")
                net_away    = bet.get("net_rating_away", "N/A")
                odds        = bet.get("odds", "N/A")
                parts       = bet.get("game", "").split(" @ ")
                away_team   = parts[0] if len(parts) == 2 else ""
                home_team   = parts[1] if len(parts) == 2 else ""
                label       = "★★★ STRONG" if edge_pct >= 8 else "★★ MODERATE" if edge_pct >= 5 else "★ SLIGHT"

                st.markdown(f"""
                <div class="nba-card">
                    <b style="font-size:18px">{bet.get('game','')}</b>
                    <span style="float:right; font-size:24px; color:#c9a84c"><b>{edge_pct:.1f}%</b> <small style="font-size:12px">{label}</small></span><br>
                    <span style="color:#888; font-size:13px">{bet.get('bet','')} · Odds: {odds}</span><br><br>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">Model: {bet.get('model_prob',0):.1f}%</span>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">Market: {bet.get('implied_prob',0):.1f}%</span>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">{home_team} Net: {net_home:+.1f}</span>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; font-size:12px">{away_team} Net: {net_away:+.1f}</span>
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

    except Exception as e:
        st.error(f"Error: {e}")


# ─── WNBA PROPS ───────────────────────────────────────────────

elif page == "🏀 WNBA Props":
    st.title("🏀 WNBA Player Props")
    st.caption("Points · Rebounds · Assists · Live FanDuel & DraftKings Lines")

    try:
        r = requests.get(f"{API_BASE}/wnba/props",
                         params={"min_edge": edge_min},
                         timeout=30)
        data = r.json()
        props = data.get("props", [])

        st.metric("Prop Edges Found", len(props))
        st.markdown("---")

        if not props:
            st.info("No prop edges above threshold right now.")
        else:
            for prop in props:
                edge_pct = prop.get("edge", 0)
                st.markdown(f"""
                <div class="edge-card edge-slight">
                    <b style="font-size:16px">{prop.get('player','')}</b> &nbsp;
                    <span style="color:#888">{prop.get('stat','').upper()} {prop.get('side','')} {prop.get('line','')} · {prop.get('bookmaker','').upper()}</span>
                    <span style="float:right; font-size:20px; color:#4a90e2"><b>{edge_pct:.1f}%</b></span><br>
                    <span style="font-size:12px; color:#888">{prop.get('game','')}</span><br><br>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; margin-right:6px; font-size:12px">Odds: {prop.get('odds','N/A')}</span>
                    <span style="background:#1e2540; padding:3px 8px; border-radius:4px; font-size:12px">Implied: {prop.get('implied','N/A')}%</span>
                </div>
                """, unsafe_allow_html=True)

        if props:
            st.markdown("---")
            st.subheader("📊 Props Table")
            st.dataframe(pd.DataFrame(props), use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Error: {e}")
