param(
    [string]$Message = "Fix calibration bugs: garbage total_line=0, spread/total grading, market breakdown"
)

function Stop-OnError($step) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "FAILED at: $step" -ForegroundColor Red
        Write-Host "Nothing further will run. Check the error above, fix it, then re-run this script." -ForegroundColor Red
        exit 1
    }
}

Write-Host "== git add -A ==" -ForegroundColor Cyan
git add -A
Stop-OnError "git add"

Write-Host ""
Write-Host "== git commit ==" -ForegroundColor Cyan
git commit -m "$Message"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Nothing to commit (working tree clean) or commit failed - continuing to pull/push anyway." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "== git pull --no-rebase ==" -ForegroundColor Cyan
git pull --no-rebase
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Pull failed or hit a merge conflict." -ForegroundColor Red
    Write-Host "Run git status to see what's conflicted, resolve it, then commit and push manually." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "== git push ==" -ForegroundColor Cyan
git push
Stop-OnError "git push"

Write-Host ""
Write-Host "Done - pushed successfully." -ForegroundColor Green
