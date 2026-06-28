@echo off
echo ================================
echo  Culture ^& Pulse — Load Props
echo ================================
echo.

cd /d C:\temp\sports_predictor

echo Opening props_today.txt for editing...
start notepad props_today.txt

echo.
echo Edit your props, SAVE the file, then close Notepad.
echo.
pause

echo.
echo Loading props into database...
py load_props.py

echo.
pause
