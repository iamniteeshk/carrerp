#Requires -Version 5.1
<#
.SYNOPSIS
  Restore from backups\YYYY-MM-DD\ into the install root.

.PARAMETER BackupDir
  Path to a dated backup folder (required).

.PARAMETER Force
  Overwrite existing config/.env/database/profiles.

.PARAMETER IncludeChrome
  Also restore profiles_browser\.

.EXAMPLE
  .\scripts\restore.ps1 -BackupDir backups\2026-07-18
  .\scripts\restore.ps1 -BackupDir backups\2026-07-18 -Force
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [switch]$Force,
    [switch]$IncludeChrome
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (Test-Path "careerpilot.pid") {
    $pidText = Get-Content "careerpilot.pid" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidText -and (Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: CareerPilot is running. Stop it before restore." -ForegroundColor Red
        exit 2
    }
}

$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$argsList = @("-m", "careerpilot.main", "restore", $BackupDir)
if ($Force) { $argsList += "--force" }
if ($IncludeChrome) { $argsList += "--chrome" }
& $py @argsList
exit $LASTEXITCODE
