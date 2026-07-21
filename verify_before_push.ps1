# verify_before_push.ps1
# Run this before pushing to GitHub — confirms every file that got
# updated today actually has today's changes on disk, not a stale
# version. Given how many times a file silently reverted today
# (download-folder duplicates, drag-and-drop overwrites), check
# everything in one shot instead of one file at a time.
#
# A PASS here means the marker text was found. It does NOT run the
# code — pair this with actually running each predictor's parity
# check before trusting the logic itself.

$checks = @(
    @{File="database.py";              Pattern="LINE_MOVEMENT_SCALE"},
    @{File="database.py";              Pattern="save_prediction_factors"},
    @{File="database.py";              Pattern="get_line_movement_adj"},
    @{File="database.py";              Pattern='bet\["edge"\]'},
    @{File="intel_feed.py";            Pattern="get_matchup_injury_adj"},
    @{File="intel_feed.py";            Pattern="SPORT_INJURY_SCALE"},
    @{File="services\odds_parser.py";  Pattern="skipping h2h market"},
    @{File="wnba_predictor.py";        Pattern="get_line_movement_adj"},
    @{File="wnba_predictor.py";        Pattern="home_factors"},
    @{File="mlb_predictor.py";         Pattern="line_adj"},
    @{File="cfb_predictor.py";         Pattern="line_adj"},
    @{File="nfl_predictor.py";         Pattern="line_adj"},
    @{File="render_job.py";            Pattern="Line Movement Alert"},
    @{File="performance_tracker.py";   Pattern="calculate_clv"},
    @{File="audit_calibration.py";     Pattern="MIN_CURVE_FIT"}
)

$failCount = 0

Write-Host "======================================================================"
Write-Host "VERIFY BEFORE PUSH"
Write-Host "======================================================================"

foreach ($check in $checks) {
    $file    = $check.File
    $pattern = $check.Pattern

    if (-not (Test-Path $file)) {
        Write-Host "[MISSING FILE] $file" -ForegroundColor Red
        $failCount++
        continue
    }

    $match = Select-String -Path $file -Pattern $pattern -Quiet

    if ($match) {
        Write-Host "[OK]   $file -> '$pattern'" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $file -> '$pattern' NOT FOUND" -ForegroundColor Red
        $failCount++
    }
}

Write-Host "======================================================================"
if ($failCount -eq 0) {
    Write-Host "ALL CHECKS PASSED — safe to git add / commit / push." -ForegroundColor Green
} else {
    Write-Host "$failCount CHECK(S) FAILED — do NOT push yet." -ForegroundColor Red
    Write-Host "Fix the flagged file(s) first (same copy-paste-into-open-file method" -ForegroundColor Yellow
    Write-Host "used all day), re-run this script, and only push once it's all green." -ForegroundColor Yellow
}
Write-Host "======================================================================"
