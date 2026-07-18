#Requires -Version 5.1
<#
.SYNOPSIS
  Register CareerPilot to start automatically at Windows logon (Task Scheduler).

.DESCRIPTION
  Creates a Scheduled Task that launches CareerPilot with the project venv
  when the current user logs on. Does not require Administrator if created
  for the current user only.

.EXAMPLE
  .\scripts\Register-CareerPilotStartup.ps1
  .\scripts\Register-CareerPilotStartup.ps1 -Remove
#>
[CmdletBinding()]
param(
    [switch]$Remove,
    [string]$TaskName = "CareerPilot"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogOut = Join-Path $Root "logs\startup.out.log"
$LogErr = Join-Path $Root "logs\startup.err.log"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName' (if it existed)."
    exit 0
}

if (-not (Test-Path $Python)) {
    Write-Host "ERROR: $Python not found. Run setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m careerpilot.main run" `
    -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "CareerPilot 24x7 job-search agent" `
    -Force | Out-Null

Write-Host "Registered scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  WorkingDirectory: $Root"
Write-Host "  Starts at user logon; restarts up to 3 times on failure."
Write-Host "Remove later with: .\scripts\Register-CareerPilotStartup.ps1 -Remove"
