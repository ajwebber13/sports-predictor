from database import get_conn
from engines.prop_engine import PropEngine


def main():
    db = get_conn()

    engine = PropEngine(db)

    print("\n=== TOP PLAYER PROPS ===\n")

    props = engine.get_top_props(10)

    if not props:
        print("No props found.")
        return

    for prop in props:
        print(
            f"{prop['player']} | "
            f"{prop['team']} | "
            f"{prop['stat']} | "
            f"Line: {prop['line']} | "
            f"Projection: {prop['projection']} | "
            f"Edge: {prop['edge']} "
            f"({prop['edge_pct']}%) | "
            f"{prop['direction'].upper()} | "
            f"Tier: {prop['tier']} | "
            f"Confidence: {prop['confidence']}"
        )


if __name__ == "__main__":
    main()