@echo off
echo.
echo ================================================
echo  Culture ^& Pulse Analytics - Git Push
echo ================================================
echo.

cd /d C:\temp\sports_predictor

echo Checking status...
git status --short
echo.

echo Staging all changes...
git add .

echo.
echo Committing...
git commit -m "update: %date%"

echo.
echo Pushing to GitHub...
git push origin main

echo.
echo ================================================
echo  Done. Check Render dashboard for redeploy.
echo ================================================
echo.
pause