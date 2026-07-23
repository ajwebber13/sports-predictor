#!/usr/bin/env bash
# cleanup_and_reorg.sh — run from the root of your sports-predictor repo
# Deletes dead app/ duplicates, old test/backtest files, and reorganizes
# backfill scripts into /backfill/<sport>/. Updates 2 workflow YAMLs to match.
set -e

echo "== Step 1: removing dead app/ duplicates =="
git rm -f app/main.py
git rm -rf app/core
git rm -rf app/schemas
git rm -f app/nba_wnba_predict.py
# app/api/ and app/__init__.py are left alone — those are live production routes

echo "== Step 1b: removing legacy pre-GitHub-Actions prediction runner =="
echo "   (superseded by render_job.py -> app/api routes; confirmed unreferenced"
echo "    by anything else in the live production path except espn_winprob.py,"
echo "    which is kept because wnba_slate_digest.py also uses it)"
git rm -f nba_wnba_predict.py
git rm -f run_daily.py
git rm -f alert_engine.py
git rm -f telegram_connector.py
git rm -f auto_predict.py
git rm -f live_ratings.py

echo "== Step 2: removing old/unused test + backtest files =="
git rm -f test_alert_format.py test_all_predictions.py test_edge_finder.py \
  test_espn.py test_live_odds.py test_matchup.py test_odds.py \
  test_odds_names.py test_officials_endpoint.py test_predictions.py \
  test_prop_engine.py
git rm -f backtest.py backtest_audit.py backtest_full.py
# backtest_engine.py is kept — it's your real validated walk-forward backtester

echo "== Step 3: building /backfill/<sport>/ structure =="
mkdir -p backfill/shared backfill/wnba backfill/nba backfill/nfl backfill/hbcu

git mv backfill.py backfill/shared/backfill.py
git mv backfill_odds.py backfill/shared/backfill_odds.py
git mv backfill_playoffs.py backfill/shared/backfill_playoffs.py
git mv backfill_results.py backfill/shared/backfill_results.py
git mv player_stats_backfill.py backfill/shared/player_stats_backfill.py

git mv backfill_h2h_wnba.py backfill/wnba/backfill_h2h_wnba.py
git mv backfill_wnba_player_log.py backfill/wnba/backfill_wnba_player_log.py

git mv nba_player_stats.py backfill/nba/nba_player_stats.py
git mv nfl_player_game_logs.py backfill/nfl/nfl_player_game_logs.py

git mv hbcu_backfill.py backfill/hbcu/hbcu_backfill.py

echo "== Step 4: patching workflow YAMLs for moved files =="
sed -i 's#python -u nfl_player_game_logs\.py#python -u backfill/nfl/nfl_player_game_logs.py#g' \
  .github/workflows/nfl_stats_backfill.yml
sed -i 's#python -u nba_player_stats\.py#python -u backfill/nba/nba_player_stats.py#g' \
  .github/workflows/nba_stats_backfill.yml

echo "== Step 5: removing _archive/ folder =="
echo "   (created by cleanup.py as a manual safety net; redundant now since git"
echo "    history already preserves everything — recoverable via git log --all)"
git rm -rf _archive

echo "== Done. Review with: git status =="
echo "== Then commit: git commit -m 'Clean up dead files, reorganize backfill by sport' =="
echo "== Then push: git push =="
