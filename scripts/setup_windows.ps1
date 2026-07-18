# Forwards to the repo-root setup script (canonical location).
$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "..\setup_windows.ps1") @args
exit $LASTEXITCODE
