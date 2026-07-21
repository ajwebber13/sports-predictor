# push_parlay_telegram.ps1 - Culture & Pulse Analytics
# Commits and pushes the Parlay Generator's Telegram wiring, and turns
# it on in the automated daily workflow (3-leg parlay every send).
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "edge_finder_alert.py",
    ".github/workflows/edge_finder_alert.yml"
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
Wire Parlay Generator into the Edge Finder Telegram alert, enable daily

- edge_finder_alert.py: new --parlay-legs flag (0/2/3/4, default 0 = off).
  When set, appends an N-leg parlay built from the same top picks
  already shown in the message (not a separately fetched pool), using
  edge_finder_parlay.build_parlay(). Missing/unavailable odds show a
  plain 'unavailable today' line instead of failing the whole alert.
  Validated end to end against a mocked send - price and payout match
  the already-confirmed live +618 / \$7.18 reference case exactly.
- edge_finder_alert.yml: automated daily send now includes --parlay-legs 3,
  so every send from here on includes a 3-leg parlay by default.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Tomorrow's 10:30 AM CT alert will include a 3-leg parlay." -ForegroundColor Green
Write-Host "To preview one manually first:" -ForegroundColor Green
Write-Host "python edge_finder_alert.py --dry-run --parlay-legs 3"
