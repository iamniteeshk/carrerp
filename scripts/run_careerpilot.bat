@echo off
REM Start CareerPilot (foreground). Windows.
cd /d "%~dp0\.."
where python >nul 2>nul || (echo ERROR: python not found. & exit /b 1)
if not exist config\config.yaml (echo ERROR: config\config.yaml missing. & exit /b 1)
if exist careerpilot.pid (echo ERROR: CareerPilot may already be running. Run scripts\stop_careerpilot.bat first. & exit /b 1)
python -m careerpilot.main run
