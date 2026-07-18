#Requires -Version 5.1
<#
.SYNOPSIS
  Allow CareerPilot Ops Dashboard (TCP 8006) from the local subnet only.

.DESCRIPTION
  Creates (or replaces) a Windows Firewall inbound rule:
    - Protocol: TCP
    - Local port: 8006 (override with -Port)
    - RemoteAddress: LocalSubnet  (192.168.x.x / 10.x.x.x / etc. on this NIC)
    - Never opens the port to the public internet

  Requires Administrator. Pair with:
    dashboard.host: 0.0.0.0
    DASHBOARD_PASSWORD=<strong password>
  and do NOT port-forward 8006 on your router.

.EXAMPLE
  .\scripts\Allow-DashboardLan.ps1
  .\scripts\Allow-DashboardLan.ps1 -Port 8006
  .\scripts\Allow-DashboardLan.ps1 -Remove
#>
[CmdletBinding()]
param(
    [int]$Port = 8006,
    [string]$RuleName = "CareerPilot Ops Dashboard (LAN only)",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Run this script in an elevated PowerShell (Run as Administrator)." -ForegroundColor Red
    exit 1
}

Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

if ($Remove) {
    Write-Host "Removed firewall rule '$RuleName' (if it existed)."
    exit 0
}

New-NetFirewallRule `
    -DisplayName $RuleName `
    -Name "CareerPilot-OpsDashboard-LAN" `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort $Port `
    -RemoteAddress LocalSubnet `
    -Profile Private, Domain `
    -Description "CareerPilot Mission Control — LAN subnet only. Do not expose to the internet." |
    Out-Null

Write-Host "Firewall rule created:" -ForegroundColor Green
Write-Host "  Name:           $RuleName"
Write-Host "  Port:           TCP $Port"
Write-Host "  RemoteAddress:  LocalSubnet (private LAN only)"
Write-Host "  Profiles:       Private, Domain"
Write-Host ""
Write-Host "Also required:" -ForegroundColor Cyan
Write-Host "  1. dashboard.host: 0.0.0.0  /  port: $Port  in config\config.yaml"
Write-Host "  2. Strong DASHBOARD_PASSWORD in .env"
Write-Host "  3. Do NOT port-forward $Port on the router"
Write-Host "Remove later: .\scripts\Allow-DashboardLan.ps1 -Remove"
