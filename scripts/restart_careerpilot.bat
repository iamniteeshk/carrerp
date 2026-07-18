@echo off
REM Restart CareerPilot.
cd /d "%~dp0\.."
call "%~dp0stop_careerpilot.bat"
timeout /t 2 /nobreak >nul
call "%~dp0_resolve_python.bat" || exit /b 1
start "CareerPilot" "%PY%" -m careerpilot.main run
