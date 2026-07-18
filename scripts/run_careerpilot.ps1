# Start CareerPilot (scheduler + dashboard) from PowerShell.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "ERROR: .venv missing. Run .\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}
Write-Host "Starting CareerPilot. Press Ctrl+C to stop." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m careerpilot.main run
