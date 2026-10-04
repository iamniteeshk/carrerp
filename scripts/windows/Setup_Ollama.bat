@echo off
setlocal EnableExtensions
cd /d "%~dp0\..\.."
echo.
echo Ollama check. This does not download models unless you type Y.
echo.
where ollama >nul 2>&1
if errorlevel 1 (
  echo FAIL: Ollama is not installed.
  echo Install it from https://ollama.com/download
  echo Then run: ollama serve
  echo Then run this file again.
  pause
  exit /b 1
)
echo Ollama program: found.
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 4).StatusCode } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo Ollama is installed but not running. Starting it ...
  start "Ollama" /MIN ollama serve
  timeout /t 3 /nobreak >nul
  powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/tags -TimeoutSec 4).StatusCode } catch { exit 1 }" >nul 2>&1
  if errorlevel 1 (
    echo FAIL: Ollama did not answer on http://127.0.0.1:11434
    echo Start it yourself with: ollama serve
    pause
    exit /b 1
  )
)
echo Ollama is reachable.
set "MISSING=0"
ollama list | findstr /C:"qwen3:8b" >nul
if errorlevel 1 (
  echo MISSING: qwen3:8b
  echo Command: ollama pull qwen3:8b
  set "MISSING=1"
) else (
  echo qwen3:8b is installed.
)
ollama list | findstr /C:"qwen3-vl:8b" >nul
if errorlevel 1 (
  echo MISSING: qwen3-vl:8b
  echo Command: ollama pull qwen3-vl:8b
  set "MISSING=1"
) else (
  echo qwen3-vl:8b is installed.
)
if "%MISSING%"=="0" (
  echo.
  echo SUCCESS: Ollama and both models are ready.
  pause
  exit /b 0
)
echo.
echo These models are large. Nothing has been downloaded.
set /p GO=Type Y to download the missing models, or press Enter to stop: 
if /I "%GO%"=="Y" (
  ollama list | findstr /C:"qwen3:8b" >nul || ollama pull qwen3:8b
  ollama list | findstr /C:"qwen3-vl:8b" >nul || ollama pull qwen3-vl:8b
) else (
  echo Skipped. Run the ollama pull commands above when you are ready.
)
echo.
pause
exit /b 0
