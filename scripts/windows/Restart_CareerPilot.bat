@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."
echo Restarting CareerPilot ...
call "%~dp0Stop_CareerPilot.bat" nopause
timeout /t 3 /nobreak >nul
call "%~dp0Start_CareerPilot.bat"
exit /b %errorlevel%
