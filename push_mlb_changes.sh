# Push script — MLB H2H + matchup + Noon Retry fix
# Run from C:\temp\sports_predictor (or wherever your repo lives)

git add mlb_h2h.py mlb_matchup.py mlb_predictor.py .github/workflows/noon_retry.yml
git commit -m "Add MLB H2H + team-vs-pitcher matchup adjustments; fix Noon Retry env vars, add 3pm trigger"
git push
