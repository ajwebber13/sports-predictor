# push_recap_fix.ps1 - Culture & Pulse Analytics
# Fixes Daily and Weekly Recap - was writing/reading Turso only, not
# Supabase. Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    ".github/workflows/daily_weekly_recap.yml",
    "auto_results.py",
    "prop_tracker.py",
    "recap_engine.py"
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
Fix Daily and Weekly Recap - Turso-only gap, 6th workflow found

- daily_weekly_recap.yml: added SUPABASE_DB_URL to all 4 jobs
  (score_results, score_props, daily_recap, weekly_recap) - same gap
  as 5 other workflows found earlier today.
- auto_results.py, prop_tracker.py, recap_engine.py: added
  load_dotenv() for local runs, same class of gap.
- recap_engine.py docstring corrected - it claimed "reads only from
  Turso," written before the Supabase migration existed. get_conn()
  itself decides the real backend from whatever env vars are present;
  the comment was just stale, not an intentional design choice.

NOT addressed here: some scheduled runs show ALL 4 jobs skipped
(e.g. run #64), which looks like github.event.schedule not matching
any of the 3 defined cron strings on some triggers - possibly GitHub
Actions schedule-delay flakiness, same class of issue as the earlier
wnba_props.yml :00/:15 collision. Not fixed yet - worth watching
after this fix lands to see if it's actually a separate problem or
was itself just a symptom of stale data confusing things.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Manually trigger 'Daily and Weekly Recap' to test." -ForegroundColor Green
Write-Host "Watch for whether score_results/score_props run cleanly, and" -ForegroundColor Green
Write-Host "whether a real recap message actually arrives in Telegram." -ForegroundColor Green
