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
        Retrieve current player prop projections.
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
        Retrieve historical player performance.
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
        Calculate model edge over sportsbook line.
        """

        return round(
            projection - line,
            2
        )


    def get_best_prop(self, player_name):
        """
        Return highest value prop opportunity
        for a specific player.
        """

        props = self.get_player_props(player_name)

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


def get_top_props(self, limit=10, sport=None):
    """
    Return highest quality prop opportunities.

    Used by:
    - Streamlit dashboard
    - API endpoints
    - betting alerts

    Normalized edge calculation:
    Prevents low lines (0.5 hits, 0.5 RBIs)
    from creating unrealistic percentages.
    """

    query = """
    SELECT
        player_name,
        team_name,
        sport,
        stat,
        line,
        projected_stat,
        projection_edge,
        projection_direction,
        projection_tier,
        confidence_tier,
        games_overall
    FROM player_props
    WHERE projected_stat IS NOT NULL
      AND confidence_tier != 'red'
      AND games_overall >= 10
    """

    params = []

    if sport:
        query += """
        AND sport = ?
        """
        params.append(sport)


    query += """
    ORDER BY projection_edge DESC
    LIMIT ?
    """

    params.append(limit)


    rows = self.db.execute(
        query,
        tuple(params)
    ).fetchall()


    results = []


    for row in rows:

        line = row["line"]
        projection = row["projected_stat"]
        edge = row["projection_edge"]


        # Normalize edge percentage
        if line >= 1:
            edge_pct = round(
                ((projection - line) / line) * 100,
                1
            )
        else:
            edge_pct = round(
                ((projection - line) / 1) * 100,
                1
            )


        results.append({

            "player": row["player_name"],
            "team": row["team_name"],
            "sport": row["sport"],
            "stat": row["stat"],

            "line": line,

            "projection": projection,

            "edge": edge,

            "edge_pct": edge_pct,

            "direction": row["projection_direction"],

            "tier": row["projection_tier"],

            "confidence": row["confidence_tier"]

        })


    return results