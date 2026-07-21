# push_discord_props.ps1 - Culture & Pulse Analytics
# Batch 2 of the Discord migration: wnba_props_alert.py,
# mlb_props_alert.py, edge_finder_alert.py -> Game Props and Edge
# Finder channel. Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "wnba_props_alert.py",
    "mlb_props_alert.py",
    "edge_finder_alert.py",
    ".github/workflows/wnba_props.yml",
    ".github/workflows/edge_finder_alert.yml"
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
Migrate props and Edge Finder alerts from Telegram to Discord (batch 2 of 3)

- wnba_props_alert.py, mlb_props_alert.py, edge_finder_alert.py:
  send_message() now routes through discord_alerts using
  DISCORD_WEBHOOK_PROPS. Also added load_dotenv() to wnba_props_alert.py
  and mlb_props_alert.py (both were missing it - same class of gap
  fixed elsewhere today; edge_finder_alert.py already had it).
- wnba_props.yml (props_alert job), edge_finder_alert.yml: swapped
  TELEGRAM_TOKEN for DISCORD_WEBHOOK_PROPS.

Validated: all 3 files' send_message() tested against a mocked Discord
webhook with real HTML content, confirmed correct markdown conversion
and payload structure.

Note: mlb_props_alert.py doesn't appear to be wired into any scheduled
workflow currently (not in wnba_props.yml despite proximity, no
separate mlb_props_alert.yml found) - file is fixed and will work
whenever/however it runs, but flagging in case that's unexpected.

These 3 files post to the "Game Props and Edge Finder" Discord channel.
One batch remains: recap_engine.py (Daily/Weekly Recaps channel),
plus render_job.py and pick_of_the_day.py still need converting.
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
Write-Host "Trigger 'Player Props' or 'Edge Finder Alert' manually to test." -ForegroundColor Green
