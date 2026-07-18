@echo off
REM Resolve CareerPilot Python: .venv → py → python3 → python
cd /d "%~dp0\.."
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
  where py >nul 2>nul && set "PY=py"
)
if not defined PY (
  where python3 >nul 2>nul && set "PY=python3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo ERROR: No Python launcher found. Install Python with the py launcher, then run setup_windows.ps1.
  exit /b 1
)
