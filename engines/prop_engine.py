"""
prop_engine.py

Player Prop Projection Engine

v2-platform

Uses existing sportsbook model tables:
- player_profiles
- player_stats_history
- player_props
"""


class PropEngine:

    def __init__(self, db):
        self.db = db


    def get_player_profile(self, player_name):
        """
        Retrieve player profile.
        """

        query = """
        SELECT *
        FROM player_profiles
        WHERE player_name = ?
        """

        return self.db.execute(
            query,
            (player_name,)
        ).fetchone()


    def get_player_props(self, player_name):
        """
        Retrieve current prop projections.
        """

        query = """
        SELECT *
        FROM player_props
        WHERE player_name = ?
        ORDER BY captured_at DESC
        """

        return self.db.execute(
            query,
            (player_name,)
        ).fetchall()


    def get_player_history(self, player_name):
        """
        Historical player performance.
        """

        query = """
        SELECT *
        FROM player_stats_history
        WHERE player_name = ?
        ORDER BY season DESC
        """

        return self.db.execute(
            query,
            (player_name,)
        ).fetchall()


    def calculate_edge(self, projection, line):
        """
        Model edge over sportsbook line.
        """

        return round(
            projection - line,
            2
        )


    def get_best_prop(self, player_name):
        """
        Return highest value prop opportunity.
        """

        props = self.get_player_props(
            player_name
        )

        if not props:
            return None


        best = max(
            props,
            key=lambda x: x["projection_edge_pct"]
            if x["projection_edge_pct"]
            else 0
        )

        return {
            "player": best["player_name"],
            "stat": best["stat"],
            "line": best["line"],
            "projection": best["projected_stat"],
            "edge": best["projection_edge"],
            "edge_pct": best["projection_edge_pct"],
            "direction": best["projection_direction"],
            "tier": best["projection_tier"],
            "confidence": best["confidence_tier"]
        }
    def get_top_props(self, limit=10):
        """
        Return highest edge props available.
        Used by dashboard.
        """

        query = """
        SELECT *
        FROM player_props
        WHERE projection_edge_pct IS NOT NULL
        ORDER BY projection_edge_pct DESC
        LIMIT ?
        """

        rows = self.db.execute(
            query,
            (limit,)
        ).fetchall()


        results = []

        for row in rows:
            results.append({
                "player": row["player_name"],
                "team": row["team_name"],
                "stat": row["stat"],
                "line": row["line"],
                "projection": row["projected_stat"],
                "edge": row["projection_edge"],
                "edge_pct": row["projection_edge_pct"],
                "direction": row["projection_direction"],
                "tier": row["projection_tier"],
                "confidence": row["confidence_tier"]
            })

        return results