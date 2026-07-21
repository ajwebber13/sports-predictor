# push_discord_recaps_final.ps1 - Culture & Pulse Analytics
# Batch 3 (final) of the Discord migration: recap_engine.py,
# pick_of_the_day.py, render_job.py, and the 3 workflows that run them.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "recap_engine.py",
    "pick_of_the_day.py",
    "render_job.py",
    ".github/workflows/daily_weekly_recap.yml",
    ".github/workflows/morning_run.yml",
    ".github/workflows/pick_of_the_day.yml"
)

$missing = $files | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Host "These expected files are missing - check they are in the right place before pushing:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  $_" }
    exit 1
}

git add $files
if ($LASTEXITCODE -ne 0) {
    Write-Host "git add failed - stopping before commit." -ForegroundColor Red
    exit 1
}

Write-Host "`nStaged changes:" -ForegroundColor Cyan
git status --short

$confirm = Read-Host "`nCommit and push these files? (y/n)"
if ($confirm -ne "y") {
    Write-Host "Aborted - nothing pushed. Files remain staged if you want to review further." -ForegroundColor Yellow
    exit 0
}

$commitMessage = @"
Migrate recaps and MLB/Lock alerts from Telegram to Discord (batch 3 of 3 - final)

- recap_engine.py: send_message() -> DISCORD_WEBHOOK_RECAPS.
- pick_of_the_day.py: send_message() -> DISCORD_WEBHOOK_GAME_PICKS.
  Added load_dotenv() (was missing).
- render_job.py: renamed send_telegram() to send_discord_alert() for
  honesty (it no longer sends Telegram), routes through
  DISCORD_WEBHOOK_GAME_PICKS. Added load_dotenv(). Confirmed it imports
  format_game_card() directly from telegram_alerts.py, so the earlier
  win-probability/team-mismatch fix already applies here automatically
  - no duplicate bug to fix separately.
- daily_weekly_recap.yml (daily_recap/weekly_recap jobs), morning_run.yml,
  pick_of_the_day.yml: swapped TELEGRAM_TOKEN for the matching Discord
  webhook secret.

Validated: all 3 files' message functions tested against a mocked
Discord webhook with real HTML content, confirmed correct markdown
conversion.

This completes the full Telegram -> Discord migration across all 8
files that ever sent alerts: discord_alerts.py (shared helper),
telegram_alerts.py, wnba_slate_digest.py, wnba_props_alert.py,
mlb_props_alert.py, edge_finder_alert.py, recap_engine.py,
pick_of_the_day.py, render_job.py.
"@

$tempMsgFile = New-TemporaryFile
Set-Content -Path $tempMsgFile -Value $commitMessage -Encoding UTF8

git commit -F $tempMsgFile.FullName
$commitExitCode = $LASTEXITCODE
Remove-Item $tempMsgFile -Force

if ($commitExitCode -ne 0) {
    Write-Host "`ngit commit failed (exit code $commitExitCode) - nothing pushed. See the error above." -ForegroundColor Red
    exit 1
}

git push
if ($LASTEXITCODE -ne 0) {
    Write-Host "`ngit push failed - the commit exists locally but never reached GitHub. Run 'git push' manually to retry." -ForegroundColor Red
    exit 1
}

Write-Host "`nConfirmed: commit and push both succeeded." -ForegroundColor Green
Write-Host "Discord migration complete across all 8 files." -ForegroundColor Green
Write-Host "Trigger 'Morning Run', 'Daily and Weekly Recap', or 'Lock of the Day' to test." -ForegroundColor Green