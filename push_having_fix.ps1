# push_having_fix.ps1 - Culture & Pulse Analytics
# Fixes HAVING clauses referencing a SELECT-list alias, which Postgres
# doesn't allow (SQLite does). Run from C:\temp\sports_predictor.

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "mlb_player_stats.py",
    "wnba_player_stats.py",
    "nba_player_stats.py",
    "star_players.py"
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
Fix HAVING clause referencing a SELECT alias - not valid on Postgres

SQLite allows HAVING to reference a SELECT-list alias (e.g. COUNT(*)
as games ... HAVING games >= 3). Postgres does not - HAVING is
evaluated before SELECT aliasing, so the alias isn't visible yet.
Fixed by using the real aggregate expression (HAVING COUNT(*) >= 3)
in all 4 affected files. This also resolves the star_players.py
warning noticed earlier today (column "games" does not exist) that
was shelved as non-blocking at the time - same root cause.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Trigger Morning Run once more to confirm a fully clean pass -" -ForegroundColor Green
Write-Host "no duplicate-key errors, no round() error, no HAVING error." -ForegroundColor Green
