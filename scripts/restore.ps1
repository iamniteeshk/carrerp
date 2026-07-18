#Requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [switch]$Force,
    [switch]$IncludeChrome
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot "_ResolvePython.ps1")
$py = Get-CareerPilotPython
if (-not $py) { Write-Host "ERROR: No Python launcher." -ForegroundColor Red; exit 1 }
$argv = @("-m", "careerpilot.main", "restore", $BackupDir)
if ($Force) { $argv += "--force" }
if ($IncludeChrome) { $argv += "--chrome" }
if ($py -eq "py") { & py @argv } else { & $py @argv }
exit $LASTEXITCODE
