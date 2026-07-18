# Start CareerPilot (foreground). Windows — prefers .venv, else py.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot "_ResolvePython.ps1")

if (-not (Test-Path "config\config.yaml")) {
    Write-Host "ERROR: config\config.yaml missing. Run .\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}
if (Test-Path "careerpilot.pid") {
    Write-Host "ERROR: CareerPilot may already be running. Run .\scripts\stop_careerpilot.bat first." -ForegroundColor Red
    exit 1
}

$py = Get-CareerPilotPython
if (-not $py) {
    Write-Host "ERROR: No Python launcher found. Run .\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}
if ($py -eq "py") {
    & py -m careerpilot.main run
} else {
    & $py -m careerpilot.main run
}
exit $LASTEXITCODE
