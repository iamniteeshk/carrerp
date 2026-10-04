@echo off
setlocal EnableExtensions
cd /d "%~dp0"
:menu
echo.
echo ========================================
echo         CAREERPILOT CONTROL
echo ========================================
echo.
echo 1. Start CareerPilot
echo 2. Stop CareerPilot
echo 3. Restart CareerPilot
echo 4. Run Doctor
echo 5. Open Dashboard
echo 6. Setup / Repair
echo 7. Exit
echo.
set "CHOICE="
set /p CHOICE=Choose: 
if "%CHOICE%"=="1" call "scripts\windows\Start_CareerPilot.bat" & goto menu
if "%CHOICE%"=="2" call "scripts\windows\Stop_CareerPilot.bat" & goto menu
if "%CHOICE%"=="3" call "scripts\windows\Restart_CareerPilot.bat" & goto menu
if "%CHOICE%"=="4" call "scripts\windows\Doctor_CareerPilot.bat" & goto menu
if "%CHOICE%"=="5" call "scripts\windows\Open_Dashboard.bat" & goto menu
if "%CHOICE%"=="6" call "scripts\windows\Install_CareerPilot.bat" & goto menu
if "%CHOICE%"=="7" exit /b 0
echo Type a number from 1 to 7.
goto menu
