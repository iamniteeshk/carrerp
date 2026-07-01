# Start CareerPilot (scheduler + dashboard) from PowerShell.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (Test-Path ".venv\Scripts\Activate.ps1") { . ".venv\Scripts\Activate.ps1" }
Write-Host "Starting CareerPilot. Press Ctrl+C to stop." -ForegroundColor Cyan
python -m careerpilot.main run
