# push_dashboard.ps1 - Culture & Pulse Analytics
# Commits and pushes the Edge Finder dashboard tab.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

# Stage only dashboard.py - the one file this change touched.
$files = @(
    "dashboard.py"
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
Add Edge Finder tab to dashboard.py

- New 5th tab between Player Props and Power Rankings
- Sport/date/top-N controls, calls edge_finder.get_edge_finder() directly
- Card per pick: rank, matchup, edge score, confidence, hit rate, projection edge, real defense rank
- Matches existing glass-card/gold theme (.cp-overall/.label/.value classes), no new CSS
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Once Render redeploys, check the new tab at:" -ForegroundColor Green
Write-Host "https://cp-picks-dashboard.onrender.com"
