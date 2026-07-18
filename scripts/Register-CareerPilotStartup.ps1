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

  Launch command prefers .venv\Scripts\python.exe when present (isolated deps);
  otherwise uses ``py -m careerpilot.main run``.

  Both modes restart the task up to 3 times on failure, every 1 minute.

.EXAMPLE
  .\scripts\Register-CareerPilotStartup.ps1
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
. (Join-Path $PSScriptRoot "_ResolvePython.ps1")

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName' (if it existed)."
    exit 0
}

# Prefer production home when repo is under ...\CareerPilot\app
$leaf = Split-Path $Root -Leaf
$HomeDir = $null
if ($leaf -eq "app") {
    $HomeDir = Split-Path $Root -Parent
    if (-not $env:CAREERPILOT_HOME) { $env:CAREERPILOT_HOME = $HomeDir }
    if (-not $env:CAREERPILOT_DATA_ROOT) {
        $env:CAREERPILOT_DATA_ROOT = Join-Path $HomeDir "data"
    }
    New-Item -ItemType Directory -Force -Path $env:CAREERPILOT_DATA_ROOT,
        (Join-Path $HomeDir "backups") | Out-Null
    # Persist for interactive / AtLogOn sessions
    [System.Environment]::SetEnvironmentVariable(
        "CAREERPILOT_HOME", $HomeDir, "User")
}

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
$wrapper = Join-Path $Root "scripts\run_careerpilot_task.cmd"
# Always regenerate a tiny wrapper so SYSTEM tasks get CAREERPILOT_HOME.
$homeLine = if ($HomeDir) { "set CAREERPILOT_HOME=$HomeDir" } else { "rem no CAREERPILOT_HOME" }
$dataLine = if ($env:CAREERPILOT_DATA_ROOT) {
    "set CAREERPILOT_DATA_ROOT=$($env:CAREERPILOT_DATA_ROOT)"
} else { "rem no CAREERPILOT_DATA_ROOT" }
if (Test-Path $venvPy) {
    $pyLaunch = "`"$venvPy`" -m careerpilot.main run"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pyLaunch = "py -m careerpilot.main run"
} else {
    Write-Host "ERROR: Neither .venv nor py launcher found. Run .\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}
@(
    "@echo off",
    "cd /d `"$Root`"",
    $homeLine,
    $dataLine,
    $pyLaunch
) | Set-Content -Path $wrapper -Encoding ASCII

$Execute = "cmd.exe"
$Argument = "/c `"$wrapper`""
$LaunchDesc = $wrapper

# Logs live under data root when configured; keep a local fallback for task stderr.
$logDir = if ($env:CAREERPILOT_DATA_ROOT) {
    Join-Path $env:CAREERPILOT_DATA_ROOT "logs"
} else {
    Join-Path $Root "logs"
}
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$action = New-ScheduledTaskAction `
    -Execute $Execute `
    -Argument $Argument `
    -WorkingDirectory $Root

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

if ($Mode -eq "LogOn") {
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
    Write-Host "  Launch:  $LaunchDesc"
    Write-Host "  WorkingDirectory: $Root"
    Write-Host "  Restart on failure: every 1 min, up to 3 times"
    Write-Host ""
    Write-Host "After the machine is stable, switch to unattended boot recovery:" -ForegroundColor Cyan
    Write-Host "  .\scripts\Register-CareerPilotStartup.ps1 -Mode Startup"
} else {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principalCheck = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principalCheck.IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Host "ERROR: -Mode Startup requires an elevated PowerShell (Run as Administrator)." -ForegroundColor Red
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
    Write-Host "  Launch:  $LaunchDesc"
    Write-Host "  WorkingDirectory: $Root"
    Write-Host "  Restart on failure: every 1 min, up to 3 times"
}

Write-Host "Remove later with: .\scripts\Register-CareerPilotStartup.ps1 -Remove"
