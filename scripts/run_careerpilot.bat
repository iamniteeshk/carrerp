@echo off
REM Start CareerPilot from the project folder using the setup virtualenv.
cd /d "%~dp0\.."
if not exist "logs" mkdir logs
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv\Scripts\python.exe missing. Run setup_windows.ps1 first.>> logs\startup.err.log
  echo ERROR: .venv\Scripts\python.exe missing. Run setup_windows.ps1 first.
  exit /b 1
)
if not exist config\config.yaml (
  echo ERROR: config\config.yaml missing. Run setup_windows.ps1 first.>> logs\startup.err.log
  echo ERROR: config\config.yaml missing. Run setup_windows.ps1 first.
  exit /b 1
)
if exist careerpilot.pid (
  set /p OLDPID=<careerpilot.pid
  tasklist /FI "PID eq %OLDPID%" | find "%OLDPID%" >nul
  if not errorlevel 1 (
    echo CareerPilot is already running ^(PID %OLDPID%^). Not starting a second copy.
    exit /b 0
  )
)
".venv\Scripts\python.exe" -m careerpilot.main run
if errorlevel 1 (
  echo CareerPilot exited with an error. See logs\ >> logs\startup.err.log
  echo CareerPilot exited with an error. See logs\
  exit /b 1
)
