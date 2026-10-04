@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0\..\.."
if not exist "logs" mkdir logs
if not exist ".venv\Scripts\python.exe" (
  echo FAIL: .venv is missing. Run Install_CareerPilot.bat first.
  pause
  exit /b 1
)
if not exist "config\config.yaml" (
  echo FAIL: config\config.yaml is missing. Run Install_CareerPilot.bat first.
  pause
  exit /b 1
)
if exist careerpilot.pid (
  set /p OLDPID=<careerpilot.pid
  tasklist /FI "PID eq !OLDPID!" | find "!OLDPID!" >nul
  if not errorlevel 1 (
    echo CareerPilot is already running ^(PID !OLDPID!^).
    echo A second copy was not started.
    pause
    exit /b 0
  )
)
echo Starting CareerPilot. This window stays open while it runs.
echo Stop it with Stop_CareerPilot.bat or Ctrl+C.
echo.
".venv\Scripts\python.exe" -m careerpilot.main run
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo FAIL: CareerPilot stopped with an error ^(exit %RC%^). See the lines above and logs\
  pause
)
exit /b %RC%
