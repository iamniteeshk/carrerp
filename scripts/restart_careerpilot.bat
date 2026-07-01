@echo off
REM Restart CareerPilot. Windows.
cd /d "%~dp0\.."
call scripts\stop_careerpilot.bat
timeout /t 2 /nobreak >nul
start "CareerPilot" python -m careerpilot.main run
echo Restarted in a new window.
