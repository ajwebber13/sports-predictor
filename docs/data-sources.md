# Data Sources

All current and planned data sources for the prediction system.

---

## Active Sources

### The Odds API
- **URL:** https://the-odds-api.com
- **Used for:** Live moneylines, spreads, totals per game
- **Markets pulled:** `h2h`, `spreads`, `totals`
- **Regions:** `us` (DraftKings, FanDuel, BetMGM)
- **Odds format:** American
- **Current plan:** Free tier — live odds only
- **Limitations:** Historical odds and player props require paid plan ($99+/month)
- **Key:** `ODDS_API_KEY` env var
- **File:** `services/odds_parser.py`

### ESPN Site API (Public)
- **URL:** `https://site.api.espn.com/apis/site/v2/sports/`
- **Used for:** Schedules, scores, box scores, injury reports, win probabilities
- **Sports:** basketball/wnba, basketball/nba, football/nfl, football/college-football
- **Auth:** None (public) — rate limited, sometimes blocks non-Render IPs
- **Files:** `wnba_slate_digest.py`, `wnba_player_stats.py`, `auto_results.py`

### ESPN Box Scores
- **URL:** `https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/summary?event={id}`
- **Used for:** Player game logs — pts, reb, ast, stl, blk per game
- **Schedule:** Runs after games complete
- **File:** `wnba_player_stats.py`

---

## Planned Sources

### The Odds API — Player Props (paid)
- **Markets:** `player_points`, `player_rebounds`, `player_assists`
- **Status:** ⏳ Requires plan upgrade
- **Will power:** `player_props` table, situational hit rate calculations
- **File to build:** `fetch_player_props.py`

### The Odds API — Historical (paid)
- **Used for:** Backfilling pre-June 22 odds gaps
- **Status:** ⏳ Requires plan upgrade
- **Workaround:** Manual CSV backfill via `patch_odds_from_csv.py`

### Public Betting % Feed
- **Candidates:** ActionNetwork, BetUS public splits
- **Used for:** Contrarian signal — flag when 80%+ public money is on one side
- **Status:** ⏳ Not yet integrated

### Referee Tendency Data
- **Source:** NBA/WNBA official game reports
- **Used for:** Foul rate tendencies, pace impact
- **Status:** ⏳ Not yet integrated

---

## Fallback Behavior

| Primary Source | Fallback | Notes |
|----------------|----------|-------|
| The Odds API live odds | ESPN fallback odds | Partial — ESPN doesn't have all markets |
| ESPN scoreboard | Cached game list | Last known games used if ESPN is blocked |
| ESPN win probs | Skipped | `ESPN_PROB_ENABLED = False` in digest |
| ESPN box scores | None | Player stats not logged if ESPN blocked |
