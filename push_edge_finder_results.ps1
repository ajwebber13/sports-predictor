# push_edge_finder_results.ps1 - Culture & Pulse Analytics
# Commits and pushes Edge Finder results tracking.
# Run from C:\temp\sports_predictor (repo root).
#
# NOTE: this assumes you already ran edge_finder_picks_schema.sql in
# the Supabase SQL editor - this script only pushes code, it does not
# touch the database.

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "edge_finder.py",
    "edge_finder_alert.py",
    "edge_finder_results.py",
    "edge_finder_picks_schema.sql"
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
Add Edge Finder results tracking

- edge_finder_picks_schema.sql: new table logging picks as sent, immutable
  (edge_score/confidence captured at pick time, not recalculated later)
- edge_finder.py: log_edge_finder_picks(), ON CONFLICT DO NOTHING
- edge_finder_alert.py: logs picks only after a real successful send,
  never on dry-run
- edge_finder_results.py: win pct / ROI (real American-odds payout) by
  confidence tier and edge-score bucket, joined against prop_results.
  Closing line movement intentionally not included - odds are only
  captured once at fetch time, no closing-line data exists to track yet.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Once tomorrow's Edge Finder Alert sends for real, check logging with:" -ForegroundColor Green
Write-Host "python edge_finder_results.py --sport wnba"
