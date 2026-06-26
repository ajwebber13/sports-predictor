# Changelog

All meaningful updates to the Culture & Pulse Analytics prediction system.

---

## [v3.0] — June 26, 2026

### Added
- **Spread picks** — model margin vs posted spread, fires when gap ≥ 3 pts
- **Totals picks** — projected total vs posted total, fires when gap ≥ 4 pts
- **Confidence tier system** — 🟢 Green / 🟡 Yellow / 🔴 Red on every pick
- **Player prop hit rate engine** (`prop_hit_rates.py`) — hit rate by opponent, home/away, B2B
- **Parlay evaluator** (`parlay_evaluator.py`) — correlated leg detection, combined probability, tier labels
- **Outcome tracking for props** — auto-scores prop results nightly in `auto_results.py`
- **Line movement tracking** (`capture_closing_lines.py`) — opening vs closing line, sharp signal detection
- **Closing lines cron** — new Render job at 4 PM CT captures pre-game lines
- **`player_props` table** — stores prop lines with hit rates and scored results
- **`line_movement` table** — stores opening/closing lines and movement per game
- **`opponent` + `home_away` columns** added to `wnba_game_log` — situational filters now possible
- **Injury suppression fix** — edge picks only suppressed when 2+ named star players are out (not any 3 roster players)
- **Duplicate alert fix** — WNBA digest owns all output, no more "No clean edges" firing after picks sent

### Changed
- Edge threshold in WNBA digest lowered from 10% to 8%
- `wnba_player_stats.py` now captures opponent and home/away on every game log entry

---

## [v2.5] — June 22, 2026

### Fixed
- Odds saving as `None` — fixed odds ingestion in `services/odds_parser.py`
- Closing odds update now fires on retry block in `render_job.py`

### Added
- `odds_history` table begins logging reliably from this date forward
- `opening_home_ml` / `opening_away_ml` now captured at morning run time

---

## [v2.0] — June 10, 2026

### Added
- WNBA slate digest (`wnba_slate_digest.py`) — morning briefing format with news, injuries, streaks, star notices
- ESPN win probability integration (disabled — ESPN blocking)
- Model divergence check between C&P model and ESPN probability
- Star player streak notices in game messages
- Injury report per team pulled from ESPN feed
- News headlines filtered by team keywords

### Changed
- Alert format redesigned — game-by-game messages instead of single summary
- Edge picks now inline per game instead of separate message

---

## [v1.5] — June 5, 2026

### Added
- `auto_results.py` — nightly result scoring, win rate tracking
- `results` table in DB
- `line_movement` table schema (data capture added later in v3.0)
- Daily and weekly recap alerts (`wnba_recap.py`)

---

## [v1.0] — June 3, 2026

### Initial launch
- Monte Carlo simulation engine for WNBA win probability
- The Odds API integration — live moneylines, spreads, totals
- Telegram alert delivery via `telegram_alerts.py`
- SQLite database (`cp_analytics.db`) — predictions, team_stats, odds_history
- Render cron deployment — morning and afternoon runs per sport
- FastAPI backend (`app/`) — `/predictions`, `/preview`, `/edge` routes
- ELO ratings engine
- Head-to-head history tracking
