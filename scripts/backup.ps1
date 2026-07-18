#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot "_ResolvePython.ps1")
$py = Get-CareerPilotPython
if (-not $py) { Write-Host "ERROR: No Python launcher." -ForegroundColor Red; exit 1 }
if ($py -eq "py") { & py -m careerpilot.main backup @args }
else { & $py -m careerpilot.main backup @args }
exit $LASTEXITCODE
