# push_edge_finder.ps1 - Culture & Pulse Analytics
# Commits and pushes today's Edge Finder work.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

# Stage only the files actually touched today, not a blanket 'git add .',
# so nothing unrelated (or half-finished) rides along in this commit.
$files = @(
    "edge_finder.py",
    "fetch_prizepicks_props.py",
    "test_edge_finder.py",
    "app/api/routes_props.py"
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
Add Edge Finder engine, tests, and /props/edge-finder endpoint

- edge_finder.py: composite prop ranking (hit rate + edge pct + defense matchup) with confidence guardrails and debug/report output modes
- test_edge_finder.py: 12 unit tests against a fake DB connection
- fetch_prizepicks_props.py: fix opponent field never reaching the DB save (opponent_team was resolved correctly but never passed to the save call)
- app/api/routes_props.py: add GET /props/edge-finder endpoint
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Once Render redeploys, test live at:" -ForegroundColor Green
Write-Host "https://sports-predictor-api-44a0.onrender.com/props/edge-finder?sport=wnba&top=5"
