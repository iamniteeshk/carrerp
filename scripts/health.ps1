#Requires -Version 5.1
<#
.SYNOPSIS
  Quick health snapshot (CPU/RAM/DB/AI/scheduler/disk/last scan).

.EXAMPLE
  .\scripts\health.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
& $py -m careerpilot.main health
exit $LASTEXITCODE
