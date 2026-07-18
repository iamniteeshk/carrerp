#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot "_ResolvePython.ps1")

$py = Get-CareerPilotPython
if (-not $py) {
    Write-Host "ERROR: No Python launcher. Run setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}
if ($py -eq "py") { & py -m pip install --upgrade pip; & py -m pip install -r requirements.txt }
else { & $py -m pip install --upgrade pip; & $py -m pip install -r requirements.txt }
exit $LASTEXITCODE
