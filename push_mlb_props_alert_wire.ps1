# push_mlb_props_alert_wire.ps1 - Culture & Pulse Analytics
# Wires mlb_props_alert.py into the daily Player Props workflow -
# it existed and worked but was never actually scheduled anywhere.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    ".github/workflows/wnba_props.yml"
)

$missing = $files | Where-Object { -not (Test-Path $_) }
if ($missing) {
    Write-Host "These expected files are missing - check they are in the right place before pushing:" -ForegroundColor Yellow
    $missing | ForEach-Object { Write-Host "  $_" }
    exit 1
}

git add $files
if ($LASTEXITCODE -ne 0) {
    Write-Host "git add failed - stopping before commit." -ForegroundColor Red
    exit 1
}

Write-Host "`nStaged changes:" -ForegroundColor Cyan
git status --short

$confirm = Read-Host "`nCommit and push these files? (y/n)"
if ($confirm -ne "y") {
    Write-Host "Aborted - nothing pushed. Files remain staged if you want to review further." -ForegroundColor Yellow
    exit 0
}

$commitMessage = @"
Wire mlb_props_alert.py into the daily Player Props workflow

mlb_props_alert.py existed, worked, and was already Discord-migrated,
but was never actually scheduled anywhere - not in this workflow
despite fetch_mlb_props living right next to it, no separate workflow
either. Added a new mlb_props_alert job, mirroring props_alert exactly:
runs at 10:22 AM CT after fetch_mlb_props, same DISCORD_WEBHOOK_PROPS
channel, same manual-trigger support.
"@

$tempMsgFile = New-TemporaryFile
Set-Content -Path $tempMsgFile -Value $commitMessage -Encoding UTF8

git commit -F $tempMsgFile.FullName
$commitExitCode = $LASTEXITCODE
Remove-Item $tempMsgFile -Force

if ($commitExitCode -ne 0) {
    Write-Host "`ngit commit failed (exit code $commitExitCode) - nothing pushed. See the error above." -ForegroundColor Red
    exit 1
}

git push
if ($LASTEXITCODE -ne 0) {
    Write-Host "`ngit push failed - the commit exists locally but never reached GitHub. Run 'git push' manually to retry." -ForegroundColor Red
    exit 1
}

Write-Host "`nConfirmed: commit and push both succeeded." -ForegroundColor Green
Write-Host "Trigger 'Player Props' manually to test - watch for the new" -ForegroundColor Green
Write-Host "mlb_props_alert job running alongside the existing 3." -ForegroundColor Green
