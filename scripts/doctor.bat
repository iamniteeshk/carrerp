@echo off
REM CareerPilot doctor. Windows.
call "%~dp0_resolve_python.bat" || exit /b 1
"%PY%" -m careerpilot.main doctor %*
