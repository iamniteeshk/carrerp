# Install dependencies and Chromium from PowerShell.
# Prefer the full production setup on a fresh machine:
#   ..\setup_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $py -m pip install --upgrade pip
& $py -m pip install -r requirements.txt
& $py -m playwright install chromium
Write-Host "Done. Prefer .\setup_windows.ps1 on a fresh PC. Then edit .env and config\config.yaml" -ForegroundColor Green
