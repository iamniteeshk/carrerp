@echo off
REM Start CareerPilot (foreground). Windows.
cd /d "%~dp0\.."
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  where python >nul 2>nul || (echo ERROR: python not found. Run setup_windows.ps1 first. & exit /b 1)
  set "PY=python"
)
if not exist config\config.yaml (echo ERROR: config\config.yaml missing. Run setup_windows.ps1 first. & exit /b 1)
if exist careerpilot.pid (
  echo ERROR: CareerPilot may already be running. Run scripts\stop_careerpilot.bat first.
  exit /b 1
)
"%PY%" -m careerpilot.main run
