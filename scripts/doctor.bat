@echo off
REM Pre-flight validation. Windows.
REM Usage: doctor.bat [--fix] [--production]
cd /d "%~dp0\.."
if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  where python >nul 2>nul || (echo ERROR: python not found. Run setup_windows.ps1 first. & exit /b 1)
  set "PY=python"
)
"%PY%" -m careerpilot.main doctor %*
exit /b %ERRORLEVEL%
