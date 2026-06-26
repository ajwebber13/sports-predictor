# Architecture

End-to-end data flow for the Culture & Pulse Analytics prediction system.

---

## System Overview

```
Data Sources          Processing              Output
─────────────         ─────────────           ──────────────
The Odds API    →     Monte Carlo Engine  →   Telegram Alerts
ESPN API        →     Edge Calculation    →   FastAPI Responses
ESPN Box Scores →     Line Movement       →   SQLite DB
                      Prop Hit Rates      →   Dashboard
```

---

## Morning Run (10 AM CT)

```
render_job.py --sport wnba
    │
    ├── get_live_odds()          ← The Odds API: h2h, spreads, totals
    ├── get_wnba_events()        ← ESPN: today's games + times
    ├── log_odds()               ← Save opening lines to odds_history
    ├── log_injuries()           ← ESPN injury report to injuries_log
    │
    └── telegram_alerts.run_alerts("wnba")
            │
            └── wnba_slate_digest.run_digest()
                    │
                    ├── get_today_games()         ← ESPN scoreboard
                    ├── fetch_model_predictions() ← FastAPI /predictions
                    ├── get_team_streaks()        ← ESPN team schedule
                    ├── get_star_notices()        ← wnba_game_log
                    ├── get_espn_win_probs()      ← ESPN (often blocked)
                    ├── get_injury_reports()      ← ESPN injury API
                    ├── get_wnba_news()           ← ESPN + Yahoo + others
                    └── format_digest()           → Telegram messages
```

---

## Prediction Engine (FastAPI)

```
GET /wnba/predictions
    │
    ├── get_wnba_events()        ← ESPN
    ├── get_live_odds()          ← The Odds API
    ├── get_team_stats()         ← team_stats table
    │
    └── WNBAPredictionEngine.predict()
            │
            ├── _expected_score()    ← off/def ratings, rest, pace
            ├── Monte Carlo (10,000 simulations)
            │       ├── home_win_prob / away_win_prob
            │       ├── projected_home / projected_away / projected_total
            │       ├── home_cover_prob / away_cover_prob
            │       └── over_prob / under_prob
            │
            ├── get_market_implied()  ← implied prob from ML odds
            ├── edge = model_prob - implied_prob
            │
            └── spread_pick / totals_pick logic
```

---

## Afternoon Run (4 PM CT)

```
capture_closing_lines.py --sport wnba
    │
    ├── get_live_odds()           ← current lines (closing snapshot)
    ├── compare to opening_home_ml from odds_history
    ├── compute movement_home / movement_away
    ├── detect sharp signal (≥8 pt movement)
    ├── update odds_history closing_home_ml / closing_away_ml
    └── write to line_movement table
```

---

## Nightly Scoring (midnight CT)

```
auto_results.py yesterday
    │
    ├── score_predictions()      ← ESPN final scores vs predictions table
    ├── write to results table
    ├── score_prop_results()     ← wnba_game_log actual stats vs player_props
    ├── print_model_report()     ← W/L by sport + edge range
    └── print_prop_report()      ← prop hit rate by player/stat
```

---

## Data Sources

| Source | Used For | Access |
|--------|----------|--------|
| The Odds API | Live odds, spreads, totals, player props | API key (free tier: h2h only; paid: historical + props) |
| ESPN Site API | Scores, schedules, box scores, injuries, win probs | Public (rate limited, sometimes blocked) |
| ESPN Box Scores | Player game logs — pts, reb, ast, stl, blk | Public |

---

## Deployment

Hosted on **Render** — all jobs run as cron services defined in `render.yaml`.

- API: always-on web service (`uvicorn`)
- Alerts: cron jobs per sport per time slot
- No persistent worker — each cron run is stateless, reads/writes to SQLite via mounted DB
