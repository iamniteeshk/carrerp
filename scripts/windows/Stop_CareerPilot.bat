@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."
set "NOPAUSE=%~1"
if not exist careerpilot.pid (
  echo CareerPilot is not running ^(no careerpilot.pid^).
  if /I not "%NOPAUSE%"=="nopause" pause
  exit /b 0
)
set /p PID=<careerpilot.pid
if "%PID%"=="" (
  echo careerpilot.pid is empty. Nothing was stopped.
  if /I not "%NOPAUSE%"=="nopause" pause
  exit /b 1
)
echo Stopping CareerPilot only ^(PID %PID%^). Other Python programs are left alone.
taskkill /PID %PID% >nul 2>&1
timeout /t 8 /nobreak >nul
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if errorlevel 1 (
  echo Stopped.
  del /f /q careerpilot.pid >nul 2>&1
  if /I not "%NOPAUSE%"=="nopause" pause
  exit /b 0
)
echo Still running. Stopping that same PID ...
taskkill /PID %PID% /T /F >nul 2>&1
del /f /q careerpilot.pid >nul 2>&1
echo Stopped.
if /I not "%NOPAUSE%"=="nopause" pause
exit /b 0
