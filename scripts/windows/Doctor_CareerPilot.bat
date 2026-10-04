@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."
if not exist ".venv\Scripts\python.exe" (
  echo FAIL: .venv is missing. Run Install_CareerPilot.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m careerpilot.main doctor --production
set "RC=%errorlevel%"
echo.
if "%RC%"=="0" (
  echo Doctor result: PASS
) else (
  echo Doctor result: FAIL
  echo Fix every FAIL line above, then run this again.
)
echo.
pause
exit /b %RC%
