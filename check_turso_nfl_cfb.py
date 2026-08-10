"""
Check the old Turso DB for NFL/CFB prediction data that may not
have migrated to Supabase.

Install first: pip install libsql-client
Run: python check_turso_nfl_cfb.py
"""

import libsql_client

TURSO_URL = "libsql://cp-analytics-ajwebber13.aws-us-east-2.turso.io"
TURSO_TOKEN = "eyJhbGciOiJFZERTQSIsInR5cCI6IkpXVCJ9.eyJhIjoicm8iLCJpYXQiOjE3ODMzOTI0NTUsImlkIjoiMDE5ZjI0ODUtN2UwMS03ZWQ0LTk2NzYtZGRjNGY0YzY2MWM5Iiwia2lkIjoiRG9ZZmhDeS1TVS1SQWZtQTAyLV81Vk5lMGZmbGlwUFhvaVdqTXp0Zy1pOCIsInJpZCI6ImE1NTRmMGY3LWI1YjctNDNjYS1hODM4LTc0MTZiNGU3YWRiZSJ9.RVY11-oRXOtwX-0DB-_mf6JkR-WMwnQ6GEeztkbJogwTPwQh3MgVEGDErpZ4q84efXWIpHdcnF51gbl0RwwxCA"


def main():
    client = libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)

    # 1. List all tables
    tables = client.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    )
    print("Tables in Turso DB:")
    for row in tables.rows:
        print(" -", row[0])

    # 2. If a `predictions` table exists there, check sport counts
    table_names = [row[0] for row in tables.rows]
    if "predictions" in table_names:
        print("\nRow counts by sport in Turso `predictions`:")
        result = client.execute(
            "SELECT sport, COUNT(*) FROM predictions GROUP BY sport;"
        )
        for row in result.rows:
            print(" -", row[0], row[1])

    client.close()


if __name__ == "__main__":
    main()
