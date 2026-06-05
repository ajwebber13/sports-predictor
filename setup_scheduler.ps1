# setup_scheduler.ps1
# ====================
# Creates Windows Task Scheduler tasks for Culture & Pulse alerts.
# Run once from PowerShell as Administrator:
#   .\setup_scheduler.ps1
#
# Creates 3 tasks:
#   1. WNBA alerts — daily at 9:00 AM
#   2. NBA alerts  — daily at 9:30 AM (during NBA season)
#   3. NCAAF alerts — Fridays at 9:00 AM (during CFB season)

$PythonPath = "C:\Users\Drew\AppData\Local\Programs\Python\Python311\python.exe"
$ScriptDir  = "C:\temp\sports_predictor"
$Script     = "C:\temp\sports_predictor\telegram_alerts.py"

Write-Host "Setting up Culture & Pulse Task Scheduler tasks..." -ForegroundColor Cyan
Write-Host ""

# ── TASK 1: WNBA Daily at 9:00 AM ─────────────────────────────
$action1  = New-ScheduledTaskAction -Execute $PythonPath -Argument "$Script --sport wnba" -WorkingDirectory $ScriptDir
$trigger1 = New-ScheduledTaskTrigger -Daily -At "9:00AM"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable

Register-ScheduledTask `
    -TaskName   "CulturePulse_WNBA_Alerts" `
    -Action     $action1 `
    -Trigger    $trigger1 `
    -Settings   $settings `
    -Description "Culture & Pulse WNBA edge alerts - fires daily at 9AM" `
    -Force

Write-Host "✅ WNBA task created: Daily at 9:00 AM" -ForegroundColor Green

# ── TASK 2: NBA Daily at 9:30 AM ──────────────────────────────
$action2  = New-ScheduledTaskAction -Execute $PythonPath -Argument "$Script --sport nba" -WorkingDirectory $ScriptDir
$trigger2 = New-ScheduledTaskTrigger -Daily -At "9:30AM"

Register-ScheduledTask `
    -TaskName   "CulturePulse_NBA_Alerts" `
    -Action     $action2 `
    -Trigger    $trigger2 `
    -Settings   $settings `
    -Description "Culture & Pulse NBA edge alerts - fires daily at 9:30AM" `
    -Force

Write-Host "✅ NBA task created: Daily at 9:30 AM" -ForegroundColor Green

# ── TASK 3: NCAAF Fridays at 9:00 AM ──────────────────────────
$action3  = New-ScheduledTaskAction -Execute $PythonPath -Argument "$Script --sport ncaaf" -WorkingDirectory $ScriptDir
$trigger3 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At "9:00AM"

Register-ScheduledTask `
    -TaskName   "CulturePulse_NCAAF_Alerts" `
    -Action     $action3 `
    -Trigger    $trigger3 `
    -Settings   $settings `
    -Description "Culture & Pulse NCAAF edge alerts - fires every Friday at 9AM" `
    -Force

Write-Host "✅ NCAAF task created: Every Friday at 9:00 AM" -ForegroundColor Green

Write-Host ""
Write-Host "All tasks created. To verify:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask | Where-Object {`$_.TaskName -like 'CulturePulse*'}"
Write-Host ""
Write-Host "To run a task manually right now:"
Write-Host "  Start-ScheduledTask -TaskName 'CulturePulse_WNBA_Alerts'"
Write-Host ""
Write-Host "To disable a task (e.g. off-season):"
Write-Host "  Disable-ScheduledTask -TaskName 'CulturePulse_NBA_Alerts'"
