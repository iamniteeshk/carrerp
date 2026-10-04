@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0\..\.."
set "PORT=5000"
if exist "config\config.yaml" (
  for /f "tokens=2 delims=: " %%P in ('findstr /R /C:"^port:" /C:"^  port:" "config\config.yaml"') do (
    set "PORT=%%P"
  )
)
set "PORT=!PORT: =!"
echo Opening http://127.0.0.1:!PORT!/
start "" "http://127.0.0.1:!PORT!/"
exit /b 0
