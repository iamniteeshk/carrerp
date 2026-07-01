@echo off
REM Pull latest code and re-install dependencies. Windows.
cd /d "%~dp0\.."
where git >nul 2>nul || (echo ERROR: git not found. & exit /b 1)
echo Pulling latest...
git pull --ff-only || (echo ERROR: git pull failed (uncommitted changes?). & exit /b 1)
python -m pip install -r requirements.txt
echo Updated. Run scripts\doctor.bat before starting.
