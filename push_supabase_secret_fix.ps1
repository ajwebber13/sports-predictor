# push_supabase_secret_fix.ps1 - Culture & Pulse Analytics
# Wires SUPABASE_DB_URL into every GitHub Actions workflow that was
# still silently falling back to Turso, and adds the new Edge Finder
# Alert workflow. Run from C:\temp\sports_predictor (repo root).
#
# IMPORTANT: this script only pushes code. It does NOT create the
# SUPABASE_DB_URL secret itself - that has to be added manually first:
#   GitHub repo -> Settings -> Secrets and variables -> Actions
#   -> New repository secret -> name it SUPABASE_DB_URL
# If the secret doesn't exist yet, these workflows will just fall
# back to Turso exactly like before - adding the env line alone does
# nothing without the secret behind it.

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$confirmSecret = Read-Host "Have you already added the SUPABASE_DB_URL secret in GitHub? (y/n)"
if ($confirmSecret -ne "y") {
    Write-Host "Add it first: GitHub repo -> Settings -> Secrets and variables -> Actions -> New repository secret -> SUPABASE_DB_URL" -ForegroundColor Yellow
    Write-Host "Then re-run this script." -ForegroundColor Yellow
    exit 0
}

$files = @(
    ".github/workflows/wnba_props.yml",
    ".github/workflows/pick_of_the_day.yml",
    ".github/workflows/publish_performance_summary.yml",
    ".github/workflows/morning_run.yml",
    ".github/workflows/edge_finder_alert.yml",
    "edge_finder_alert.py"
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
Wire SUPABASE_DB_URL into GitHub Actions, add Edge Finder Alert workflow

- Every scheduled workflow (props fetch/alert, pick of the day, performance
  summary, morning run) was only passing TURSO_DATABASE_URL/TURSO_AUTH_TOKEN,
  so the automated pipeline has been silently writing to Turso instead of
  Supabase since the 7/14 migration, while Render and local runs used
  Supabase - two databases diverging daily. Added SUPABASE_DB_URL to each.
- New edge_finder_alert.yml: runs edge_finder_alert.py at 10:30 AM CT daily,
  after the Player Props fetch/alert, wired to SUPABASE_DB_URL from the start.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. In GitHub Actions, manually trigger 'Player Props' (workflow_dispatch)" -ForegroundColor Green
Write-Host "once to confirm it now writes to Supabase instead of Turso before trusting" -ForegroundColor Green
Write-Host "tomorrow's scheduled run." -ForegroundColor Green
