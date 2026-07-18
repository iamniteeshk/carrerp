#Requires -Version 5.1
<#
.SYNOPSIS
  Create a dated production backup under backups\YYYY-MM-DD\

.PARAMETER IncludeChrome
  Also copy profiles_browser\ (large; contains login sessions).

.EXAMPLE
  .\scripts\backup.ps1
  .\scripts\backup.ps1 -IncludeChrome
#>
[CmdletBinding()]
param([switch]$IncludeChrome)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
$argsList = @("-m", "careerpilot.main", "backup")
if ($IncludeChrome) { $argsList += "--chrome" }
& $py @argsList
exit $LASTEXITCODE
