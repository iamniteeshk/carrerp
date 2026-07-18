@echo off
REM Install requirements. Windows — always use -m pip via py/venv.
call "%~dp0_resolve_python.bat" || exit /b 1
"%PY%" -m pip install --upgrade pip || (echo ERROR: pip upgrade failed. & exit /b 1)
"%PY%" -m pip install -r requirements.txt || (echo ERROR: pip install failed. & exit /b 1)
"%PY%" -m playwright install chromium || (echo ERROR: playwright browser install failed. & exit /b 1)
echo OK: requirements + Playwright Chromium installed.
