# push_recap_split.ps1
# Pushes the 3-file workflow split and removes the old daily_weekly_recap.yml.

$ErrorActionPreference = "Stop"
$repoPath = "C:\temp\sports_predictor"
Set-Location $repoPath

Write-Host "== git status before =="
git status

$oldFile = ".github\workflows\daily_weekly_recap.yml"
if (Test-Path $oldFile) {
    git rm $oldFile
    if ($LASTEXITCODE -ne 0) { Write-Host "git rm FAILED"; exit 1 }
    Write-Host "Removed old $oldFile"
} else {
    Write-Host "$oldFile not found, already removed, skipping."
}

git add -A
if ($LASTEXITCODE -ne 0) { Write-Host "git add FAILED"; exit 1 }

git commit -m "Split daily/weekly recap workflow into 3 separate single-cron files"
if ($LASTEXITCODE -ne 0) { Write-Host "git commit FAILED"; exit 1 }

git push
if ($LASTEXITCODE -ne 0) { Write-Host "git push FAILED"; exit 1 }

Write-Host ""
Write-Host "== DONE =="
Write-Host "Pushed successfully. Check github.com/ajwebber13/sports-predictor/actions"
Write-Host "and confirm all 3 workflows show up separately, and daily_weekly_recap.yml is gone."