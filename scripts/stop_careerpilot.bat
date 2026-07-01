@echo off
REM Stop a running CareerPilot. Windows.
cd /d "%~dp0\.."
if not exist careerpilot.pid (echo Not running (no careerpilot.pid). & exit /b 0)
set /p PID=<careerpilot.pid
echo Stopping CareerPilot (PID %PID%)...
taskkill /PID %PID% /T /F >nul 2>nul
if errorlevel 1 (echo Process not found; cleaning up.) else (echo Stopped.)
del /f /q careerpilot.pid >nul 2>nul
