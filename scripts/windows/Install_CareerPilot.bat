@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."
echo.
echo CareerPilot setup
echo Folder: %CD%
echo.
if not exist "careerpilot\main.py" (
  echo FAIL: This file is not inside a CareerPilot repository.
  echo Double-click it from the cloned CareerPilot folder.
  echo.
  pause
  exit /b 1
)
if not exist "requirements.txt" (
  echo FAIL: requirements.txt is missing.
  pause
  exit /b 1
)
if not exist "deployment_input\config.yaml" (
  echo FAIL: deployment_input\config.yaml is missing.
  echo Clone the production-ready branch. Do not copy files by hand.
  pause
  exit /b 1
)
where py >nul 2>&1
if %errorlevel%==0 (
  set "PYLAUNCH=py -3"
) else (
  set "PYLAUNCH=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv ...
  %PYLAUNCH% -m venv .venv
  if errorlevel 1 (
    echo FAIL: Could not create .venv. Install Python 3.10 or newer, then run this again.
    pause
    exit /b 1
  )
)
echo Installing Python packages ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
  echo FAIL: pip could not be upgraded.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo FAIL: Could not install requirements.txt.
  pause
  exit /b 1
)
echo Installing the Playwright browser ...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
  echo FAIL: Playwright Chromium did not install.
  pause
  exit /b 1
)
echo Installing config and the six profiles from deployment_input ...
".venv\Scripts\python.exe" -m careerpilot.main setup
if errorlevel 1 (
  echo FAIL: deployment_input did not validate. Read the lines above.
  pause
  exit /b 1
)
echo.
echo Running Doctor. Secrets in .env are still required before a full PASS.
echo.
".venv\Scripts\python.exe" -m careerpilot.main doctor --production
set "RC=%errorlevel%"
echo.
if not "%RC%"=="0" (
  echo Doctor reported FAIL. Config and profiles are installed.
  echo Fill .env ^(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DASHBOARD_USER, DASHBOARD_PASSWORD^), then run Doctor_CareerPilot.bat.
  echo Ollama and the two models must also be installed. Use Setup_Ollama.bat.
) else (
  echo SUCCESS. Next: fill .env if you have not already, then Start_CareerPilot.bat.
)
echo.
pause
exit /b %RC%
