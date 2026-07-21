# push_winprob_mismatch_fix.ps1 - Culture & Pulse Analytics
# Fixes a real bug where WNBA alert cards showed the wrong team paired
# with the wrong win probability whenever the recommended (edge) pick
# was the away team - underdog value bets looked like strong favorites.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "app/api/routes_wnba.py",
    "telegram_alerts.py"
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
Fix WNBA alert win-probability/team mismatch on away-team edge picks

Root cause: routes_wnba.py's model_prob field is set to whichever
team's edge is bigger (home or away), not always the home team - but
telegram_alerts.py's format_game_card() always assumed model_prob was
the home team's probability. When the recommended bet was the away
team, this silently swapped the win-probability split and could show
the wrong team's number next to the Pick line - making underdog value
bets look like near-coin-flip favorites.

- routes_wnba.py: both /wnba/edges and /wnba/predictions now also
  return explicit home_win_prob/away_win_prob fields alongside the
  existing model_prob, removing the ambiguity at the source.
- telegram_alerts.py: format_game_card() uses the new explicit fields
  when available (falls back to the old derivation only for older API
  responses without them). Also fixed the Pick line itself to always
  match bet_label's actual recommended team rather than independently
  re-deriving "winner" from a probability comparison, which can
  legitimately disagree with bet_label on value/underdog picks.

Validated against a reconstructed version of the exact broken alert
(LA Sparks @ Chicago Sky) - output is now internally consistent.
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
Write-Host "Render should auto-redeploy the API service (routes_wnba.py lives there)." -ForegroundColor Green
Write-Host "Trigger WNBA Morning Alert manually to see a corrected alert." -ForegroundColor Green
