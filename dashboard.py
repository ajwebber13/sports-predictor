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
        '<div style="font-family:\'Bebas Neue\',sans-serif;font-size:32px;color:#fff;">Culture & Pulse Picks</div>'
        '<div style="color:#8a7d55;font-size:12px;margin-bottom:20px;">Enter password to continue</div>'
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

# ---------- STYLE: Culture & Pulse Boardroom/ESPN brand + Outlier-style data density ----------
# Brand: black #0A0A0A background, gold #D4AF37 primary accent, ticker gold #feb400,
# Bebas Neue for headlines, Oswald for labels, DM Sans for body — per CP brand identity.
# Win/loss still uses green/red since that's the clearest convention for that specific signal.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Oswald:wght@500;600;700&family=DM+Sans:wght@400;500;700&display=swap');

.stApp { background-color: #0A0A0A; }
#MainMenu, footer, header { visibility: hidden; }
* { font-family: 'DM Sans', -apple-system, sans-serif; }

.cp-header { display: flex; align-items: center; justify-content: space-between; padding: 4px 0 20px 0; margin-bottom: 8px; border-bottom: 1px solid #2a2416; }
.cp-header .brand { display: flex; align-items: center; gap: 10px; }
.cp-header .dot { width: 9px; height: 9px; border-radius: 50%; background: #feb400; box-shadow: 0 0 8px #feb400; }
.cp-header h1 { font-family: 'Bebas Neue', sans-serif; font-size: 34px; font-weight: 400; color: #ffffff; margin: 0; letter-spacing: 1px; }
.cp-header .sub { font-family: 'Oswald', sans-serif; color: #8a7d55; font-size: 11px; font-weight: 500; letter-spacing: 1.5px; text-transform: uppercase; }

.cp-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
.cp-card { background: #131209; border: 1px solid #2a2416; border-radius: 10px; padding: 16px 18px; }
.cp-card .sport-name { font-family: 'Oswald', sans-serif; color: #8a7d55; font-size: 11px; font-weight: 600; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 8px; }
.cp-card .record { color: #ffffff; font-size: 26px; font-weight: 800; line-height: 1; letter-spacing: -0.5px; }
.cp-card .pct-row { display: flex; align-items: center; gap: 5px; margin-top: 8px; }
.cp-card .pct-up { color: #3ecf8e; font-size: 13px; font-weight: 700; }
.cp-card .pct-down { color: #ff5c5c; font-size: 13px; font-weight: 700; }

.cp-overall { background: linear-gradient(135deg, #1a1608, #0A0A0A); border: 1px solid #3a2f14; border-left: 3px solid #D4AF37; border-radius: 10px; padding: 18px 22px; margin-bottom: 20px; }
.cp-overall .label { font-family: 'Oswald', sans-serif; color: #8a7d55; font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 4px; font-weight: 600; }
.cp-overall .value { color: #ffffff; font-size: 30px; font-weight: 800; letter-spacing: -0.5px; }
.cp-overall .value .pct { color: #D4AF37; }

.tier-green { background: #16311f; color: #3ecf8e; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; }
.tier-yellow { background: #332c11; color: #e8c547; padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; }

h3 { font-family: 'Oswald', sans-serif !important; color: #8a7d55 !important; font-weight: 600 !important; font-size: 14px !important; text-transform: uppercase; letter-spacing: 1.5px; }

section[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; border: 1px solid #2a2416; }
.stMultiSelect [data-baseweb="tag"] { background-color: #2a2416 !important; color: #D4AF37 !important; border: 1px solid #D4AF3733 !important; }
hr { border-color: #2a2416 !important; }
.stTabs [data-baseweb="tab-list"] { gap: 4px; }
.stTabs [data-baseweb="tab"] { background-color: #131209; border-radius: 8px 8px 0 0; color: #8a7d55; font-family: 'Oswald', sans-serif; padding: 8px 18px; }
.stTabs [aria-selected="true"] { color: #D4AF37 !important; border-bottom: 2px solid #D4AF37 !important; }
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
    cols = ["date", "sport", "player_name", "team_name", "opponent", "stat", "line",
            "over_odds", "hit_rate_overall", "confidence_tier",
            "actual_value", "hit", "team_won"]

    query_with_results = """
        SELECT pp.date, pp.sport, pp.player_name, pp.team_name, pp.opponent,
               pp.stat, pp.line, pp.over_odds, pp.hit_rate_overall, pp.confidence_tier,
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
        query_no_results = """
            SELECT date, sport, player_name, team_name, opponent,
                   stat, line, over_odds, hit_rate_overall, confidence_tier
            FROM player_props
            ORDER BY date DESC
        """
        cur = conn.execute(query_no_results)
        rows = cur.fetchall()
        base_cols = cols[:10]
        df = pd.DataFrame(rows, columns=base_cols)
        df["actual_value"] = None
        df["hit"] = None
        df["team_won"] = None
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
        col1, col2 = st.columns(2)
        with col1:
            sport_filter = st.multiselect("Sport", options=df["sport"].unique(), default=list(df["sport"].unique()), key="g_sport")
        with col2:
            status_filter = st.multiselect("Result", options=["WIN", "LOSS", "PENDING"], default=["WIN", "LOSS", "PENDING"], key="g_status")

        filtered = df[df["sport"].isin(sport_filter) & df["status"].isin(status_filter)].copy()

        # Pull the team name being bet on out of the "bet" field (e.g. "Miami Marlins ML")
        # to look up its logo — matches the sport's team ID map when available.
        def pick_logo(row):
            team_guess = row["bet"].replace(" ML", "").strip()
            return team_logo_url(row["sport"], team_guess)
        filtered["pick_logo"] = filtered.apply(pick_logo, axis=1)

        sorted_full = filtered.sort_values("date", ascending=False).reset_index(drop=True)
        display_cols = ["pick_logo", "date", "sport", "game", "bet", "odds", "edge", "final_score", "status"]

        event = st.dataframe(
            sorted_full[display_cols],
            use_container_width=True, hide_index=True,
            column_config={
                "pick_logo": st.column_config.ImageColumn(""),
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
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px;margin-top:16px;padding-top:14px;border-top:1px solid #2a2416;">
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

        def prop_status(row):
            if pd.isna(row["hit"]):
                return "PENDING"
            return "HIT" if row["hit"] == 1 else "MISS"
        props_df["status"] = props_df.apply(prop_status, axis=1)

        def tier_badge(t):
            t = (t or "").strip()
            if "🟢" in t or t.lower() == "green":
                return '<span class="tier-green">🟢 PLAY</span>'
            if "🟡" in t or t.lower() == "yellow":
                return '<span class="tier-yellow">🟡 MONITOR</span>'
            return t

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
        col1, col2, col3 = st.columns(3)
        with col1:
            sport_f = st.multiselect("Sport", options=props_df["sport"].unique(), default=list(props_df["sport"].unique()), key="p_sport")
        with col2:
            status_f = st.multiselect("Result", options=["HIT", "MISS", "PENDING"], default=["HIT", "MISS", "PENDING"], key="p_status")
        with col3:
            tiers = props_df["confidence_tier"].dropna().unique()
            tier_f = st.multiselect("Tier", options=list(tiers), default=list(tiers), key="p_tier")

        pf = props_df[
            props_df["sport"].isin(sport_f)
            & props_df["status"].isin(status_f)
            & (props_df["confidence_tier"].isin(tier_f) | props_df["confidence_tier"].isna())
        ].copy()

        st.write(f"**{len(pf)} props**")
        for _, row in pf.sort_values("date", ascending=False).iterrows():
            result_color = {"HIT": "#3ecf8e", "MISS": "#ff5c5c", "PENDING": "#6b6b6b"}[row["status"]]
            actual = f"{row['actual_value']:.1f}" if pd.notna(row["actual_value"]) else "—"

            opp_logo = team_logo_url(row["sport"], row["opponent"])
            logo_html = (
                f'<img src="{opp_logo}" style="width:22px;height:22px;object-fit:contain;margin-left:6px;vertical-align:middle;">'
                if opp_logo else ""
            )
            avatar = initials_avatar(row["player_name"])

            st.markdown(f"""
<div class="cp-card" style="margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;">
<div style="display:flex;align-items:center;gap:12px;">
{avatar}
<div>
<div style="color:#fff;font-weight:700;font-size:15px;">{row['player_name']} <span style="color:#6b6b6b;font-weight:500;">vs {row['opponent']}</span>{logo_html}</div>
<div style="color:#6b6b6b;font-size:13px;margin-top:4px;">Over {row['line']} {row['stat'].upper()} · {row['date']}</div>
</div>
</div>
<div style="text-align:right;">
{tier_badge(row['confidence_tier'])}
<div style="color:{result_color};font-weight:800;font-size:14px;margin-top:6px;">{row['status']} ({actual})</div>
</div>
</div>
""", unsafe_allow_html=True)
