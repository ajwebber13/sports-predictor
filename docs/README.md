# Culture & Pulse Analytics — Sports Predictor

A sports prediction and betting analytics system that generates ML, spread, and totals picks across WNBA, NBA, NFL, NCAAF, and NCAAB. Delivers picks via Telegram alerts on an automated cron schedule.

---

## What It Does

- Pulls live odds and game data from The Odds API and ESPN
- Runs a Monte Carlo simulation engine (10,000 iterations per game) to generate win probability, projected scores, spread cover probability, and over/under probability
- Compares model probability to market-implied probability to find edge
- Fires Telegram alerts with picks, confidence tiers, injury context, and news
- Auto-scores results nightly and tracks win rate and ROI

---

## Sports Covered

| Sport | Status | Alert Schedule |
|-------|--------|----------------|
| WNBA  | ✅ Active | Daily 10 AM CT + 4 PM CT |
| NBA   | ✅ Active (in-season) | Daily 10 AM CT + 4 PM CT |
| NFL   | ✅ Active (in-season) | Sun 9 AM, Thu 5 PM, Mon 5 PM CT |
| NCAAF | ✅ Active (in-season) | Sat 9 AM, Tue–Fri 5 PM CT |
| NCAAB | ✅ Active (in-season) | Daily 10 AM CT + 4 PM CT |

---

## Running Locally

**Requirements:** Python 3.11+

```bash
git clone https://github.com/ajwebber13/sports-predictor.git
cd sports-predictor
pip install -r requirements.txt
```

**Environment variables required:**
```
ODDS_API_KEY=your_key
TELEGRAM_TOKEN=your_token
TELEGRAM_CHANNEL=@your_channel
```

**Run the API:**
```bash
uvicorn app.main:app --reload
```

**Run a manual alert (dry run):**
```bash
python wnba_slate_digest.py --dry-run
python render_job.py --sport wnba
```

**Score yesterday's results:**
```bash
python auto_results.py yesterday
```

**Test the parlay evaluator:**
```bash
python parlay_evaluator.py
python parlay_evaluator.py --example
```

**Test prop hit rates:**
```bash
python prop_hit_rates.py --player "A'ja Wilson" --stat pts --line 22.5 --opponent "Connecticut Sun" --home-away away
```

---

## Project Structure

```
sports-predictor/
├── app/                    # FastAPI application
│   ├── main.py             # App entry point
│   └── api/                # Route handlers per sport
├── services/               # Shared services
│   └── odds_parser.py      # Odds API fetch + parse
├── docs/                   # Technical documentation
├── data/                   # Prediction JSON cache
├── dashboard/              # Streamlit dashboard
├── wnba_predictor.py       # WNBA Monte Carlo engine
├── wnba_slate_digest.py    # WNBA morning digest + alerts
├── render_job.py           # Main cron entry point
├── auto_results.py         # Nightly result scoring
├── prop_hit_rates.py       # Player prop hit rate engine
├── parlay_evaluator.py     # Multi-leg parlay evaluator
├── capture_closing_lines.py # Afternoon closing line capture
├── telegram_alerts.py      # Telegram send functions
├── database.py             # DB init + write functions
├── cp_analytics.db         # SQLite database
└── render.yaml             # Render cron configuration
```

---

## Telegram Channel

**Culture & Pulse Picks** — picks, props, and analytics for entertainment only.
