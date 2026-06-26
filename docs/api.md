# API

FastAPI backend documentation. Base URL on Render: `https://sports-predictor-api.onrender.com`

---

## Running Locally

```bash
uvicorn app.main:app --reload
# Available at http://localhost:8000
# Docs at http://localhost:8000/docs
```

---

## WNBA Routes

### `GET /wnba/predictions`
Returns today's WNBA game predictions.

**Query params:**
| Param | Default | Description |
|-------|---------|-------------|
| `simulations` | 10000 | Monte Carlo iterations |

**Response:**
```json
{
  "count": 2,
  "best_bets": [
    {
      "game": "Chicago Sky @ Las Vegas Aces",
      "bet": "Las Vegas Aces ML",
      "model_prob": 71.3,
      "implied_prob": 58.2,
      "edge": 0.131,
      "odds": -180,
      "projected": "89.2-76.4",
      "projected_total": 165.6,
      "posted_spread": -9.5,
      "posted_total": 164.5,
      "pred_margin": 12.8,
      "spread_pick": "Aces -9.5",
      "spread_cover_prob": 61.2,
      "spread_edge": 3.3,
      "over_prob": 54.1,
      "under_prob": 45.9,
      "home_record": "14-6",
      "away_record": "8-12",
      "home_rest": 2,
      "away_rest": 1
    }
  ]
}
```

---

### `GET /wnba/edges`
Returns games where model edge exceeds a minimum threshold.

**Query params:**
| Param | Default | Description |
|-------|---------|-------------|
| `simulations` | 10000 | Monte Carlo iterations |
| `min_edge` | 3.0 | Minimum edge % to include |

**Response:** Same structure as `/wnba/predictions`

---

### `GET /wnba/preview`
Run a prediction for a specific matchup.

**Query params:**
| Param | Required | Description |
|-------|----------|-------------|
| `home` | Yes | Home team name |
| `away` | Yes | Away team name |
| `simulations` | No (10000) | Monte Carlo iterations |

**Example:**
```
GET /wnba/preview?home=Las Vegas Aces&away=Minnesota Lynx
```

**Response:**
```json
{
  "game": "Minnesota Lynx @ Las Vegas Aces",
  "home_win_prob": 68.4,
  "away_win_prob": 31.6,
  "projected": "87.1-74.3",
  "projected_total": 161.4,
  "home_cover_prob": 62.1,
  "away_cover_prob": 37.9,
  "over_prob": 48.3,
  "under_prob": 51.7,
  "home_record": "14-6",
  "away_record": "11-9"
}
```

---

## Health Check

### `GET /`
```json
{"status": "ok", "service": "C&P Sports Predictor"}
```

---

## Notes

- All predictions use today's live odds from The Odds API
- If The Odds API is unavailable, spread/total fields will be null
- ESPN team data is cached — if ESPN is blocked, last known stats are used
- Simulations default to 10,000 — increase for higher precision, decrease for speed
