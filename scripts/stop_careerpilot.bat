@echo off
REM Stop a running CareerPilot. Windows — try graceful TERM first, then force.
cd /d "%~dp0\.."
if not exist careerpilot.pid (echo Not running (no careerpilot.pid). & exit /b 0)
set /p PID=<careerpilot.pid
echo Stopping CareerPilot (PID %PID%) gracefully...
REM Graceful: taskkill without /F sends WM_CLOSE to console apps when possible.
taskkill /PID %PID% >nul 2>nul
timeout /t 8 /nobreak >nul
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if errorlevel 1 (
  echo Stopped gracefully.
  del /f /q careerpilot.pid >nul 2>nul
  exit /b 0
)
echo Still running — forcing stop...
taskkill /PID %PID% /T /F >nul 2>nul
if errorlevel 1 (echo Process not found; cleaning up.) else (echo Forced stop complete.)
del /f /q careerpilot.pid >nul 2>nul
