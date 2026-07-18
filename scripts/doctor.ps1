# Run CareerPilot pre-flight checks from PowerShell.
# Usage:
#   .\scripts\doctor.ps1
#   .\scripts\doctor.ps1 -Fix
#   .\scripts\doctor.ps1 -Fix -Production
param(
    [switch]$Fix,
    [switch]$Production
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = $null
if (Test-Path ".venv\Scripts\python.exe") {
    $py = (Resolve-Path ".venv\Scripts\python.exe").Path
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $py = "python"
} else {
    Write-Host "ERROR: Python not found. Run .\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

$argsList = @("-m", "careerpilot.main", "doctor")
if ($Fix) { $argsList += "--fix" }
if ($Production) { $argsList += "--production" }
& $py @argsList
exit $LASTEXITCODE
