@echo off
REM Start CareerPilot (foreground). Windows.
call "%~dp0_resolve_python.bat" || exit /b 1
if not exist config\config.yaml (
  echo ERROR: config\config.yaml missing. Run setup_windows.ps1 first.
  exit /b 1
)
if exist careerpilot.pid (
  echo ERROR: CareerPilot may already be running. Run scripts\stop_careerpilot.bat first.
  exit /b 1
)
"%PY%" -m careerpilot.main run
