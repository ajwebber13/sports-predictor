@echo off
echo Moving docs files to docs folder...

move "%~dp0README.md" "%~dp0docs\README.md"
move "%~dp0changelog.md" "%~dp0docs\changelog.md"
move "%~dp0architecture.md" "%~dp0docs\architecture.md"
move "%~dp0database.md" "%~dp0docs\database.md"
move "%~dp0alerts.md" "%~dp0docs\alerts.md"
move "%~dp0models.md" "%~dp0docs\models.md"
move "%~dp0api.md" "%~dp0docs\api.md"
move "%~dp0data-sources.md" "%~dp0docs\data-sources.md"

echo Done.
pause
