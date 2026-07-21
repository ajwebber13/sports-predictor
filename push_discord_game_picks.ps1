# push_discord_game_picks.ps1 - Culture & Pulse Analytics
# Pushes the first Discord migration batch: discord_alerts.py (shared
# send helper), telegram_alerts.py + wnba_slate_digest.py (converted
# to Discord), and the workflow that runs them.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "discord_alerts.py",
    "telegram_alerts.py",
    "wnba_slate_digest.py",
    ".github/workflows/wnba_morning_alert.yml"
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
Migrate WNBA game-pick alerts from Telegram to Discord (batch 1 of 3)

- discord_alerts.py: new shared send helper - webhook-based (simpler
  than Telegram's bot token + chat_id), converts the small HTML subset
  these alerts use (<b>/<i>/&amp;) to Discord markdown, auto-splits
  anything over Discord's 2000-char hard limit. Validated: conversion,
  splitting, and success/failure paths all tested against realistic
  content and mocked sends.
- telegram_alerts.py, wnba_slate_digest.py: send_message() now routes
  through discord_alerts instead of the Telegram bot API. Every
  existing call site keeps working unchanged since the HTML-to-markdown
  conversion happens transparently inside send_message(). Also added
  load_dotenv() to wnba_slate_digest.py (was missing, same class of
  gap fixed elsewhere today).
- wnba_morning_alert.yml: swapped TELEGRAM_TOKEN for
  DISCORD_WEBHOOK_GAME_PICKS.

These two files post to the "Game Day Picks" Discord channel. Two more
batches remain: Game Props/Edge Finder channel (wnba_props_alert.py,
mlb_props_alert.py, edge_finder_alert.py) and Daily/Weekly Recaps
channel (recap_engine.py), plus render_job.py (MLB game picks) and
pick_of_the_day.py still need converting.
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
Write-Host "Trigger 'WNBA Morning Alert' manually to see the first real Discord message." -ForegroundColor Green
