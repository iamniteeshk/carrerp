@echo off
REM Safe update wrapper.
cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update_careerpilot.ps1" %*
exit /b %ERRORLEVEL%
