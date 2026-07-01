@echo off
REM Pre-flight validation. Windows.
cd /d "%~dp0\.."
where python >nul 2>nul || (echo ERROR: python not found. & exit /b 1)
if not exist config\config.yaml (echo ERROR: config\config.yaml missing. Copy config.example.yaml to it. & exit /b 1)
if not exist .env echo WARNING: .env missing; copy .env.example to .env and add your keys.
python -m careerpilot.main doctor
