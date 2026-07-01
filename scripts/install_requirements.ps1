# Install dependencies and Chromium from PowerShell.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
Write-Host "Done. Copy .env.example to .env and edit config\config.yaml" -ForegroundColor Green
