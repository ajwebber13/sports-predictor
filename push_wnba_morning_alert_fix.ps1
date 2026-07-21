# push_wnba_morning_alert_fix.ps1 - Culture & Pulse Analytics
# Fixes the WNBA Morning Alert workflow (daily 8:30 AM CT game picks) -
# it was silently writing all WNBA predictions to Turso, not Supabase,
# since the migration. Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    ".github/workflows/wnba_morning_alert.yml",
    "telegram_alerts.py"
)

$missing = $files | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Host "These expected files are missing - check they are in the right place before pushing:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  $_" }
    exit 1
}

git add $files

Write-Host "`nStaged changes:" -ForegroundColor Cyan
git status --short

$confirm = Read-Host "`nCommit and push these files? (y/n)"
if ($confirm -ne "y") {
    Write-Host "Aborted - nothing pushed. Files remain staged if you want to review further." -ForegroundColor Yellow
    exit 0
}

$commitMessage = @"
Fix WNBA Morning Alert - was writing predictions to Turso, not Supabase

- wnba_morning_alert.yml: added SUPABASE_DB_URL, same gap as the 4
  workflows fixed earlier today, just a 5th one we hadn't found yet.
  This is the daily 8:30 AM CT scheduled job that logs WNBA game
  predictions via telegram_alerts.py - likely the actual primary
  source of WNBA model_prob data, meaning the earlier "only 1 real
  prediction post-incident" finding was probably measuring the wrong
  database, not the true state.
- telegram_alerts.py: added load_dotenv() for local runs, same class
  of gap fixed in several other files today.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. This should mean real WNBA model_prob data has actually" -ForegroundColor Green
Write-Host "been accumulating in Turso this whole time. Worth re-running" -ForegroundColor Green
Write-Host "check_model_prob_coverage.py after tomorrow's alert to see the" -ForegroundColor Green
Write-Host "real picture now that new data lands in Supabase." -ForegroundColor Green
