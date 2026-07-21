# push_mlb_timeout_fix.ps1 - Culture & Pulse Analytics
# Fixes the MLB grading gap: raises render_job.py's timeout and adds
# per-request caching to mlb_data.py's get_team_stats().
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "render_job.py",
    "mlb_data.py"
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
Fix MLB grading gap - timeout stopgap + team-stats caching

- render_job.py: raised the sport-edges fetch timeout 60s -> 150s (both
  the main call and the retry path). MLB's edges route does 4 real
  external calls per game (2x get_team_stats, weather, odds) with no
  caching or parallelization - on a normal 10-15 game day that's ~60
  sequential calls, easily exceeding 60s. This is a stopgap, not the
  full fix.
- mlb_data.py: added lru_cache to get_team_stats() so the same team is
  only fetched once per process run instead of once per game it
  appears in (doubleheaders, or /predictions + /edges both running the
  same day). Verified no caller mutates the returned dict, so caching
  is safe. Confirmed via test: repeat call for the same team hits the
  cache, not the network.
- NOT included: parallelizing the per-game loop, which is the deeper
  fix for the remaining distinct-team calls. Flagged as a separate,
  bigger change worth its own focused pass with live timing feedback.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Trigger Morning Run manually to test before tomorrow's scheduled run:" -ForegroundColor Green
Write-Host "GitHub repo -> Actions -> Morning Run -> Run workflow"
