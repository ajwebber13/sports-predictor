# push_recap_and_wnba_alert.ps1 - Culture & Pulse Analytics
# Combined, corrected push for the WNBA Morning Alert and Daily/Weekly
# Recap fixes. Earlier scripts had a real bug: git commit -m $var
# without quoting caused PowerShell to split the multi-line commit
# message into separate arguments, which git then tried to interpret
# as file paths - the commit silently failed both times, but the
# script printed "Done" anyway since it never checked for errors.
# This version writes the commit message to a temp file and uses
# git commit -F <file>, which sidesteps the quoting problem entirely,
# and checks the actual exit code of each git command before claiming
# success. Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    ".github/workflows/wnba_morning_alert.yml",
    "telegram_alerts.py",
    ".github/workflows/daily_weekly_recap.yml",
    "auto_results.py",
    "prop_tracker.py",
    "recap_engine.py"
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
Fix WNBA Morning Alert and Daily/Weekly Recap - Turso-only, missing dispatch fallback

- wnba_morning_alert.yml, telegram_alerts.py: added SUPABASE_DB_URL and
  load_dotenv() - this is the daily 8:30 AM CT WNBA game-pick alert,
  likely the actual primary source of WNBA model_prob data, which had
  been silently writing to Turso only since the migration.
- daily_weekly_recap.yml, auto_results.py, prop_tracker.py,
  recap_engine.py: same SUPABASE_DB_URL/load_dotenv() fix, plus added
  a workflow_dispatch fallback to daily_recap/weekly_recap's if:
  conditions so a manual trigger can actually test the real Telegram
  send, not just the scoring steps.
- recap_engine.py docstring corrected (used to say "Turso only,"
  written before Supabase existed - get_conn() decides the real
  backend from env vars present, the comment was just stale).

Two earlier push attempts for these same changes failed silently -
git commit -m `$var without quoting let PowerShell split the message
into separate args, which git then tried to read as file paths. This
script uses git commit -F <tempfile> instead, which avoids that
entirely, and checks exit codes before reporting success.
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
Write-Host "Manually trigger 'WNBA Morning Alert' and 'Daily and Weekly Recap' to test." -ForegroundColor Green
