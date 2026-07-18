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
. (Join-Path $PSScriptRoot "_ResolvePython.ps1")

$py = Get-CareerPilotPython
if (-not $py) {
    Write-Host "ERROR: No Python launcher found. Install Python with the py launcher, then run .\setup_windows.ps1" -ForegroundColor Red
    exit 1
}

$argsList = @("-m", "careerpilot.main", "doctor")
if ($Fix) { $argsList += "--fix" }
if ($Production) { $argsList += "--production" }
if ($py -eq "py") { & py @argsList } else { & $py @argsList }
exit $LASTEXITCODE
