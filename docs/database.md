# Database

SQLite database: `cp_analytics.db`

---

## Tables

### `predictions`
Every pick the model generates before a game.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| date | TEXT | Game date (YYYY-MM-DD) |
| sport | TEXT | wnba, nba, nfl, ncaaf, ncaab |
| game | TEXT | "Away @ Home" |
| home_team | TEXT | |
| away_team | TEXT | |
| bet | TEXT | e.g. "Las Vegas Aces ML" |
| odds | INTEGER | American ML odds at pick time |
| model_prob | REAL | Model win probability (%) |
| implied_prob | REAL | Market-implied probability (%) |
| edge | REAL | model_prob - implied_prob |
| home_record | TEXT | e.g. "12-5" |
| away_record | TEXT | |
| home_rest | INTEGER | Days rest |
| away_rest | INTEGER | |
| home_injuries | TEXT | Injury list |
| away_injuries | TEXT | |
| predicted_winner | TEXT | |
| created_at | TEXT | ISO timestamp |

---

### `results`
Scored outcomes — populated nightly by `auto_results.py`.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| date | TEXT | |
| sport | TEXT | |
| game | TEXT | |
| home_team | TEXT | |
| away_team | TEXT | |
| home_score | INTEGER | Final score |
| away_score | INTEGER | Final score |
| actual_winner | TEXT | |
| prediction_id | INTEGER | FK → predictions.id |
| correct | INTEGER | 1 = correct, 0 = wrong |
| edge_at_pick | REAL | Edge at time of pick |
| odds_at_pick | INTEGER | |
| updated_at | TEXT | |

---

### `odds_history`
Opening and closing lines per game.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| date | TEXT | |
| sport | TEXT | |
| home_team | TEXT | |
| away_team | TEXT | |
| home_ml | INTEGER | Current ML at capture time |
| away_ml | INTEGER | |
| home_implied | REAL | Implied probability (%) |
| away_implied | REAL | |
| spread | REAL | Posted spread |
| over_under | REAL | Posted total |
| opening_home_ml | INTEGER | Morning open line |
| opening_away_ml | INTEGER | |
| closing_home_ml | INTEGER | Pre-game close (4 PM CT) |
| closing_away_ml | INTEGER | |
| source | TEXT | odds_api, espn, manual_backfill |
| captured_at | TEXT | ISO timestamp |

---

### `line_movement`
Opening vs closing line comparison — populated by `capture_closing_lines.py`.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| date | TEXT | |
| sport | TEXT | |
| home_team | TEXT | |
| away_team | TEXT | |
| opening_home_ml | INTEGER | |
| opening_away_ml | INTEGER | |
| closing_home_ml | INTEGER | |
| closing_away_ml | INTEGER | |
| movement_home | INTEGER | closing - opening (pts) |
| movement_away | INTEGER | |
| sharp_signal | TEXT | Description if ≥8 pt move |
| captured_at | TEXT | |

---

### `player_props`
Player prop lines with hit rates — populated when Odds API props feed is active.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| date | TEXT | |
| sport | TEXT | |
| player_name | TEXT | |
| team_name | TEXT | |
| opponent | TEXT | |
| home_away | TEXT | home or away |
| stat | TEXT | pts, reb, ast, stl, blk |
| line | REAL | Prop line (e.g. 18.5) |
| over_odds | INTEGER | American odds for Over |
| under_odds | INTEGER | |
| hit_rate_overall | REAL | % of games player hit this line |
| hit_rate_vs_opp | REAL | % vs this specific opponent |
| hit_rate_home_away | REAL | % home or away |
| hit_rate_b2b | REAL | % on back-to-backs |
| games_overall | INTEGER | Sample size |
| games_vs_opp | INTEGER | |
| games_home_away | INTEGER | |
| confidence_tier | TEXT | green, yellow, red |
| result | TEXT | hit or miss (scored nightly) |
| actual_value | REAL | Player's actual stat |
| scored_at | TEXT | |
| source | TEXT | odds_api, manual |
| captured_at | TEXT | |

---

### `wnba_game_log`
Per-game player stats — populated by `wnba_player_stats.py`.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| date | TEXT | YYYYMMDD format |
| player_name | TEXT | |
| team_name | TEXT | |
| minutes | REAL | |
| pts | REAL | |
| reb | REAL | |
| ast | REAL | |
| stl | REAL | |
| blk | REAL | |
| fg_pct | REAL | |
| three_pct | REAL | |
| ft_pct | REAL | |
| opponent | TEXT | Opposing team (populated June 26+ forward) |
| home_away | TEXT | home or away |

---

### `team_stats`
Season-level team ratings — updated by data pipeline.

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| sport | TEXT | |
| season | TEXT | e.g. "2026" |
| team_name | TEXT | |
| wins | INTEGER | |
| losses | INTEGER | |
| pts_per_game | REAL | |
| pts_allowed | REAL | |
| net_rating | REAL | off_rating - def_rating |
| off_rating | REAL | Points scored per 100 possessions |
| def_rating | REAL | Points allowed per 100 possessions |
| pace | REAL | Possessions per game |
| home_wins | INTEGER | |
| home_losses | INTEGER | |
| away_wins | INTEGER | |
| away_losses | INTEGER | |
| last_10_wins | INTEGER | |
| rest_days_avg | REAL | |
| source | TEXT | |
| updated_at | TEXT | |

---

## Other Tables

| Table | Description |
|-------|-------------|
| `advanced_metrics` | Per-team advanced stats (SRS, SOS, etc.) |
| `bankroll_log` | Kelly criterion sizing log |
| `elo_history` | ELO rating history per team per date |
| `elo_ratings` | Current ELO ratings |
| `head_to_head` | Historical H2H results |
| `home_away_splits` | Team performance split by location |
| `injuries_log` | Injury reports per team per date |
| `player_profiles` | Player metadata |
| `player_stats_history` | Season averages per player |
| `situational_factors` | Rest, travel, and schedule context |
