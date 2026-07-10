from database import get_conn

conn = get_conn()
c = conn.cursor()

tables = [
    "team_stats",
    "advanced_metrics",
    "elo_ratings",
    "home_away_splits",
    "player_profiles",
    "player_stats_history",
    "player_props",
    "prop_results",
    "wnba_game_log",
    "mlb_game_log",
    "predictions",
    "results"
]


for table in tables:
    try:
        c.execute(f"SELECT COUNT(*) FROM {table}")
        count = c.fetchone()[0]

        print(f"{table:<25} {count:,} rows")

    except Exception as e:
        print(f"{table}: ERROR {e}")


conn.close()