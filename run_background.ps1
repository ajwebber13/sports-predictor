# run_background.ps1 - Culture & Pulse Analytics
# Launches any command as a detached background process, with output
# logged to a timestamped file instead of tying up your terminal.
#
# Usage:
#   .\run_background.ps1 "python cfb_player_game_logs.py backfill 20250823"
#
# Output goes to .\logs\<timestamp>.log - check progress any time with:
#   Get-Content .\logs\<timestamp>.log -Tail 20 -Wait

param(
    [Parameter(Mandatory=$true)]
    [string]$Command
)

if (-not (Test-Path "logs")) {
    New-Item -ItemType Directory -Path "logs" | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = "logs\$timestamp.log"

Write-Host "Starting in background, logging to $logFile" -ForegroundColor Cyan

$process = Start-Process -FilePath "powershell" `
    -ArgumentList "-NoProfile", "-Command", $Command `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError "$logFile.err" `
    -WindowStyle Hidden `
    -PassThru

Write-Host "Running as PID $($process.Id)" -ForegroundColor Green
Write-Host ""
Write-Host "Check progress:" -ForegroundColor Yellow
Write-Host "  Get-Content $logFile -Tail 20 -Wait"
Write-Host ""
Write-Host "Stop it early if needed:" -ForegroundColor Yellow
Write-Host "  Stop-Process -Id $($process.Id)"
