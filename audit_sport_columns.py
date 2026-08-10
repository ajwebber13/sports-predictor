"""
Sport model audit - checks fill rate of key columns per sport
in the shared `predictions` table.

Run: python audit_sport_columns.py
"""

import os
import psycopg2

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres.ksylbbhrrfyvzxirwyai:Cultureandpulse216!@aws-1-us-east-2.pooler.supabase.com:5432/postgres",
)

SPORTS = ["mlb", "nfl", "cfb", "wnba", "nba"]

CHECK_FIELDS = [
    "projected_home",
    "projected_away",
    "projected_margin",
    "projected_total",
    "model_prob",
    "confidence",
]


def audit():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    header = f"{'SPORT':<6} {'ROWS':<7}"
    for f in CHECK_FIELDS:
        header += f" {f[:10]:<11}"
    header += " VERDICT"
    print(header)
    print("-" * len(header))

    for sport in SPORTS:
        cur.execute(
            "SELECT COUNT(*) FROM predictions WHERE sport = %s",
            (sport,),
        )
        total_rows = cur.fetchone()[0]

        if total_rows == 0:
            print(f"{sport:<6} {'0':<7} -- no rows for this sport --")
            continue

        fill_pcts = {}
        for field in CHECK_FIELDS:
            cur.execute(
                f"SELECT COUNT(*) FROM predictions WHERE sport = %s AND {field} IS NOT NULL",
                (sport,),
            )
            filled = cur.fetchone()[0]
            fill_pcts[field] = round(100 * filled / total_rows)

        has_score = fill_pcts["projected_home"] > 50 and fill_pcts["projected_away"] > 50
        has_margin = fill_pcts["projected_margin"] > 50
        has_total = fill_pcts["projected_total"] > 50

        if has_score and has_margin and has_total:
            verdict = "WIRE-IT-UP (populated)"
        elif has_score and not (has_margin and has_total):
            verdict = "WIRE-IT-UP (derive from score)"
        else:
            verdict = "BUILD-FROM-SCRATCH"

        row = f"{sport:<6} {total_rows:<7}"
        for f in CHECK_FIELDS:
            row += f" {str(fill_pcts[f]) + '%':<11}"
        row += f" {verdict}"
        print(row)

    cur.close()
    conn.close()


if __name__ == "__main__":
    audit()