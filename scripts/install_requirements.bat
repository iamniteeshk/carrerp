@echo off
REM Install dependencies and the browser. Windows.
cd /d "%~dp0\.."
where python >nul 2>nul || (echo ERROR: python not found. Install Python 3.10+ and add to PATH. & exit /b 1)
echo Installing Python dependencies...
python -m pip install -r requirements.txt || (echo ERROR: pip install failed. & exit /b 1)
echo Installing the configured browser (Playwright)...
python -m playwright install chromium || (echo ERROR: playwright browser install failed. & exit /b 1)
echo Done. Next: copy .env.example .env  ^&  copy config.example.yaml config\config.yaml  ^&  edit them  ^&  scripts\doctor.bat
