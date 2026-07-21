# push_ai_prop_analyzer.ps1 - Culture & Pulse Analytics
# Commits and pushes the AI Prop Analyzer and its Telegram wiring.
# Run from C:\temp\sports_predictor (repo root).

if (-not (Test-Path ".git")) {
    Write-Host "Not in the repo root (no .git folder found). cd into C:\temp\sports_predictor first." -ForegroundColor Red
    exit 1
}

$files = @(
    "ai_prop_analyzer.py",
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
Add AI Prop Analyzer, wire into Edge Finder Telegram alert

- ai_prop_analyzer.py: templated (not LLM-based) natural-language
  reasoning per pick, built from hit rate / projection edge / defense
  matchup - the same inputs Edge Finder already validated end to end.
  Deterministic: same numbers always produce the same sentence.
  Deliberately does not touch predictions.model_prob or any
  game-level confidence number, since that metric is still flagged
  as uncalibrated.
- edge_finder_alert.py: includes the analysis paragraph under each
  pick by default; --brief flag restores the old stat-line-only format.
"@

git commit -m $commitMessage
git push

Write-Host "`nDone. Next Edge Finder Alert send will include the analysis by default." -ForegroundColor Green
Write-Host "Use --brief on any manual run to skip it."
