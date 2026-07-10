"""
prop_engine.py

Player Prop Projection Engine

v2-platform foundation

Handles:
- Player profiles
- Historical performance
- Prop projections
- Betting edge calculations
- Confidence scoring
"""


class PropEngine:

    def __init__(self, db):
        self.db = db


    def get_player_profile(self, player_id):
        """
        Retrieve player information.
        """

        query = """
        SELECT *
        FROM player_profiles
        WHERE id = ?
        """

        return self.db.execute(
            query,
            (player_id,)
        ).fetchone()


    def get_player_history(self, player_id):
        """
        Retrieve historical player performance.
        """

        query = """
        SELECT *
        FROM player_stats_history
        WHERE player_id = ?
        ORDER BY id DESC
        """

        return self.db.execute(
            query,
            (player_id,)
        ).fetchall()


    def calculate_edge(self, projection, line):
        """
        Calculate model advantage over sportsbook line.
        """

        return round(projection - line, 2)


    def calculate_confidence(self, sample_size, hit_rate):
        """
        Basic confidence score.
        """

        confidence = (
            min(sample_size / 20, 1)
            * hit_rate
        )

        return round(confidence * 100, 1)


    def generate_pick(
        self,
        player,
        market,
        line,
        projection,
        hit_rate,
        sample_size
    ):

        return {
            "player": player,
            "market": market,
            "line": line,
            "projection": projection,
            "edge": self.calculate_edge(
                projection,
                line
            ),
            "confidence": self.calculate_confidence(
                sample_size,
                hit_rate
            )
        }