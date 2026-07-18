@echo off
REM One-command Windows production setup. Prefer PowerShell.
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\setup_windows.ps1" %*
exit /b %ERRORLEVEL%
