@echo off
REM Update deps (legacy helper). Prefer scripts\update_careerpilot.ps1.
cd /d "%~dp0\.."
call "%~dp0_resolve_python.bat" || exit /b 1
if exist requirements.lock (
  "%PY%" -m pip install -r requirements.lock
) else (
  "%PY%" -m pip install -r requirements.txt
)
