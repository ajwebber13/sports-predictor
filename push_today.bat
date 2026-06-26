@echo off
echo.
echo ================================================
echo  Culture ^& Pulse Analytics — Git Push
echo ================================================
echo.

cd /d C:\temp\sports_predictor

echo Checking status...
git status --short
echo.

echo Staging all changes...
git add .

echo.
echo Committing...
git commit -m "feat: odds backfill, line movement, prop hit rates, parlay evaluator, confidence tiers, outcome tracking

- backfill_odds.py: historical odds backfill script (API-based)
- patch_odds_from_csv.py: CSV-based manual odds patcher
- odds_backfill_template.csv: filled template with June 3-17 closing lines
- migrate_game_log.py: one-time migration adds opponent/home_away to wnba_game_log
- capture_closing_lines.py: afternoon cron captures closing lines + computes movement
- prop_hit_rates.py: player prop hit rate engine with situational filters
- parlay_evaluator.py: multi-leg parlay evaluator with correlated leg detection
- auto_results.py: added prop outcome scoring and prop hit rate report
- wnba_slate_digest.py: confidence tiers (green/yellow/red), line movement display,
  injury suppression uses star player list, duplicate no-edge message fixed
- wnba_player_stats.py: captures opponent + home_away in game log going forward
- telegram_alerts.py: WNBA digest owns alerts, no duplicate summary message
- render.yaml: added wnba-closing-lines cron at 4 PM CT"

echo.
echo Pushing to GitHub...
git push origin main

echo.
echo ================================================
echo  Done. Check Render dashboard for redeploy.
echo ================================================
echo.
pause
