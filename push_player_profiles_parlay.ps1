# push_player_profiles_parlay.ps1 - Culture & Pulse Analytics
# Commits and pushes Player Profiles + Parlay Generator, plus the
# get_edge_finder() odds fix found while testing the parlay.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "player_profile.py",
    "dashboard.py",
    "edge_finder_parlay.py",
    "edge_finder.py"
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
Add Player Profiles and Parlay Generator, fix missing odds in get_edge_finder()

- player_profile.py: read-only profile report (bio + recent game log +
  current props + templated form-trend notes), no new data collection
- dashboard.py: new Player Profiles tab (6th tab) - search, header card,
  notes, props table, recent-game line chart
- edge_finder_parlay.py: combines top Edge Finder picks into a real
  N-leg parlay price, reusing pick_of_the_day.py's proven American-odds
  combination math; validated against its own +264 reference case
- edge_finder.py: fixed get_edge_finder()'s SQL SELECT, which never
  included over_odds/under_odds - every pick returned by Edge Finder
  (API, dashboard, alert, everywhere) has been missing odds fields
  since the original build; found while testing the parlay generator,
  fixed, all 12 unit tests still pass unchanged
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Test the parlay fix with:" -ForegroundColor Green
Write-Host "python edge_finder_parlay.py --date 2026-07-15 --sport wnba --legs 3"