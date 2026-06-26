# Models

How predictions are generated, model versions, and methodology.

---

## Prediction Engine

**File:** `wnba_predictor.py`  
**Class:** `WNBAPredictionEngine`  
**Method:** Monte Carlo simulation (10,000 iterations per game)

---

## How It Works

### 1. Expected Score Calculation
For each team, the engine calculates an expected score using:

- **Offensive rating** (points per 100 possessions)
- **Opponent defensive rating**
- **Pace adjustment** (possessions per game)
- **Rest adjustment** — each additional rest day = +0.5 pts; B2B = -2.5 pts
- **Home court advantage** — +3.5 pts for home team
- **Turnover adjustment** — deviation from league average (13.5 TOV/game)

```python
expected_score = base_score * (opp_def_rating / league_avg_def) * pace_factor + rest_adj + home_adj + to_adj
```

### 2. Monte Carlo Simulation
Both expected scores are used as the mean of a normal distribution with a fixed standard deviation (`SCORE_STD_DEV`). The engine runs 10,000 simulations and counts outcomes:

| Output | How Calculated |
|--------|----------------|
| `home_win_prob` | % of simulations where home > away |
| `away_win_prob` | % of simulations where away > home |
| `projected_home` | Mean of home score distribution |
| `projected_away` | Mean of away score distribution |
| `projected_total` | Mean of combined score distribution |
| `home_cover_prob` | % of simulations where margin > posted spread |
| `away_cover_prob` | % of simulations where margin < posted spread |
| `over_prob` | % of simulations where total > posted total |
| `under_prob` | % of simulations where total < posted total |

### 3. Edge Calculation
```
edge = model_win_prob - market_implied_prob
```
Market-implied probability is derived from the moneyline using standard American odds conversion.

### 4. Pick Thresholds

| Pick Type | Threshold |
|-----------|-----------|
| ML edge (hard pick) | edge ≥ 10% (render_job) |
| ML edge (digest display) | edge ≥ 8% |
| Spread pick | model margin vs posted spread ≥ 3 pts |
| Totals pick | model projected total vs posted total ≥ 4 pts |

---

## Confidence Tiers

Applied per pick before sending alert:

| Tier | Criteria |
|------|----------|
| 🟢 GREEN | model_prob ≥ 60% AND edge ≥ 10% |
| 🟡 YELLOW | model_prob 55–59% OR edge 8–9% |
| 🔴 RED | below threshold — no pick |

---

## Model Versions

### v3 — Current (June 26, 2026)
- Spread picks added (margin vs posted spread)
- Totals picks added (projected total vs posted total)
- Confidence tier system (Green/Yellow/Red) on every pick
- Player prop hit rate engine with situational filters
- Parlay evaluator with correlated leg detection

### v2 — (June 10, 2026)
- WNBA slate digest format
- Injury suppression on edge picks
- ESPN divergence check (disabled)
- Star player streak notices

### v1 — Initial (June 3, 2026)
- Monte Carlo win probability
- Moneyline edge vs market
- ELO ratings integration
- Basic Telegram alerts

---

## Supporting Models

### ELO Ratings (`elo_ratings.py`)
- Standard ELO system, K-factor = 20
- Updated after each game result
- Used as a secondary signal for power rating context

### Ensemble Model (`ensemble_model.py`)
- Combines Monte Carlo output with ELO ratings
- Currently experimental — not active in main prediction flow

---

## Known Limitations

- **Opponent-adjusted stats** — raw offense/defense ratings, not adjusted for strength of schedule yet
- **Model confidence decay** — predictions don't decay as game time approaches and new info arrives
- **Pace data** — using season-level pace, not recent-game pace
- **Player availability** — injuries pulled from ESPN but not weighted in the score model directly (only affects edge suppression in alerts)
