#Requires -Version 5.1
<#
.SYNOPSIS
  Register CareerPilot to start automatically via Windows Task Scheduler.

.DESCRIPTION
  Default (recommended for the first few days):
    -Mode LogOn
    Starts at user logon — easy to debug (desktop session, same user profile).

  After the box is stable (true unattended recovery after power outage):
    -Mode Startup
    Starts at system boot, runs whether the user is logged on or not
    (registers as SYSTEM; requires Administrator).

  Both modes restart the task up to 3 times on failure, every 1 minute.

.EXAMPLE
  # First days — easier to debug
  .\scripts\Register-CareerPilotStartup.ps1

  # Stable dedicated machine — survive power restore without login
  .\scripts\Register-CareerPilotStartup.ps1 -Mode Startup

  .\scripts\Register-CareerPilotStartup.ps1 -Remove
#>
[CmdletBinding()]
param(
    [ValidateSet("LogOn", "Startup")]
    [string]$Mode = "LogOn",

    [switch]$Remove,
    [string]$TaskName = "CareerPilot"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"

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

# Restart every 1 minute, up to 3 times (both modes).
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

if ($Mode -eq "LogOn") {
    # Phase 1: current-user logon — no Admin required; best for first validation.
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "CareerPilot 24x7 (At LogOn — debug-friendly)" `
        -Force | Out-Null

    Write-Host "Registered scheduled task '$TaskName' (Mode=LogOn)." -ForegroundColor Green
    Write-Host "  Trigger: At LogOn (user $($env:USERNAME))"
    Write-Host "  WorkingDirectory: $Root"
    Write-Host "  Restart on failure: every 1 min, up to 3 times"
    Write-Host ""
    Write-Host "After the machine is stable, switch to unattended boot recovery:" -ForegroundColor Cyan
    Write-Host "  .\scripts\Register-CareerPilotStartup.ps1 -Mode Startup"
} else {
    # Phase 2: At Startup — survives power restore without interactive login.
    # Requires Administrator (SYSTEM principal).
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principalCheck = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principalCheck.IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "ERROR: -Mode Startup requires an elevated PowerShell (Run as Administrator)." -ForegroundColor Red
        Write-Host "  Right-click PowerShell -> Run as administrator, then re-run:"
        Write-Host "  .\scripts\Register-CareerPilotStartup.ps1 -Mode Startup"
        exit 1
    }

    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal `
        -UserId "NT AUTHORITY\SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "CareerPilot 24x7 (At Startup — unattended, SYSTEM)" `
        -Force | Out-Null

    Write-Host "Registered scheduled task '$TaskName' (Mode=Startup)." -ForegroundColor Green
    Write-Host "  Trigger: At Startup (SYSTEM — runs whether user is logged on or not)"
    Write-Host "  WorkingDirectory: $Root"
    Write-Host "  Restart on failure: every 1 min, up to 3 times"
    Write-Host ""
    Write-Host "Ensure Windows sleep/hibernate are disabled, and install path" -ForegroundColor Yellow
    Write-Host "is readable by SYSTEM (e.g. C:\CareerPilot)."
}

Write-Host "Remove later with: .\scripts\Register-CareerPilotStartup.ps1 -Remove"
