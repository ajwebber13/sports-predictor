# push_round_fix.ps1 - Culture & Pulse Analytics
# Fixes the Postgres ROUND(double precision, integer) bug in
# mlb/wnba/nba_player_stats.py. Run fix_sequences.sql in Supabase
# SEPARATELY first - this script only pushes code, not the DB fix.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "mlb_player_stats.py",
    "wnba_player_stats.py",
    "nba_player_stats.py"
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
Fix ROUND(double precision, integer) does not exist on Postgres

Postgres's 2-argument ROUND() only works on the numeric type, not
double precision/float - SQLite never distinguished between them, so
this broke silently after the migration. Cast each AVG(...) to
::numeric before rounding. Same bug found in all 3 files (mlb/wnba/nba
player_stats.py), 9 instances each, fixed via the same pattern in all.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Remember: fix_sequences.sql still needs to be run in Supabase" -ForegroundColor Yellow
Write-Host "separately - this only fixed the ROUND() bug, not the ID collision bug." -ForegroundColor Yellow
