-- edge_finder_picks — one immutable row per pick actually SENT in an
-- Edge Finder alert. This is deliberately separate from player_props
-- (which gets overwritten/re-projected as the day's data changes) —
-- results tracking needs to know what the score/confidence WAS at the
-- moment the pick went out, not what it recalculates to later.

CREATE TABLE IF NOT EXISTS edge_finder_picks (
    id                    SERIAL PRIMARY KEY,
    date                  TEXT NOT NULL,
    sport                 TEXT NOT NULL,
    player_name           TEXT NOT NULL,
    stat                  TEXT NOT NULL,
    line                  NUMERIC,
    direction             TEXT,
    edge_score            NUMERIC,
    confidence            TEXT,
    hit_rate_overall      NUMERIC,
    games_overall         INTEGER,
    projection_edge_pct   NUMERIC,
    defense_factor        NUMERIC,
    logged_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (date, sport, player_name, stat)
);