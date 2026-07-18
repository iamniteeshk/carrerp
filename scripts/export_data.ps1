#Requires -Version 5.1
<#
.SYNOPSIS
  Export CareerPilot user data for migration to another PC.

.DESCRIPTION
  Copies the entire data root (config, .env, profiles, database, browser
  sessions, reports, …) into a portable folder or zip. Application code
  (the Git repo under app/) is NOT included — clone that separately.

  Destination layout:
    <OutDir>\careerpilot_data\   # full data root
    <OutDir>\careerpilot_data.zip  (when -Compress)

.PARAMETER OutDir
  Folder that will receive the export (created if missing).

.PARAMETER IncludeChrome
  Include Playwright browser profiles (LinkedIn/Naukri cookies/sessions).
  Large; omit if you will re-login on the new PC.

.PARAMETER IncludeBackups
  Also copy the dated backups root.

.PARAMETER Compress
  Create careerpilot_data.zip in addition to the folder copy.

.EXAMPLE
  .\scripts\export_data.ps1 -OutDir D:\migrate
  .\scripts\export_data.ps1 -OutDir D:\migrate -IncludeChrome -Compress
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutDir,

    [switch]$IncludeChrome,
    [switch]$IncludeBackups,
    [switch]$Compress
)

$ErrorActionPreference = "Stop"
$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $AppRoot

# Resolve data root the same way Python does.
if ($env:CAREERPILOT_DATA_ROOT) {
    $DataRoot = $env:CAREERPILOT_DATA_ROOT
} elseif ($env:CAREERPILOT_HOME) {
    $DataRoot = Join-Path $env:CAREERPILOT_HOME "data"
} elseif ((Split-Path $AppRoot -Leaf) -eq "app") {
    $DataRoot = Join-Path (Split-Path $AppRoot -Parent) "data"
} elseif (Test-Path (Join-Path $AppRoot "data")) {
    $DataRoot = Join-Path $AppRoot "data"
} else {
    $DataRoot = $AppRoot
}

if ($env:CAREERPILOT_BACKUPS_ROOT) {
    $BackupsRoot = $env:CAREERPILOT_BACKUPS_ROOT
} elseif ($env:CAREERPILOT_HOME) {
    $BackupsRoot = Join-Path $env:CAREERPILOT_HOME "backups"
} elseif ((Split-Path $DataRoot -Leaf) -eq "data") {
    $BackupsRoot = Join-Path (Split-Path $DataRoot -Parent) "backups"
} else {
    $BackupsRoot = Join-Path $AppRoot "backups"
}

Write-Host "App root:     $AppRoot"
Write-Host "Data root:    $DataRoot"
Write-Host "Backups root: $BackupsRoot"

if (-not (Test-Path $DataRoot)) {
    Write-Host "ERROR: data root not found: $DataRoot" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$Dest = Join-Path $OutDir "careerpilot_data"
if (Test-Path $Dest) {
    Write-Host "ERROR: $Dest already exists — choose another OutDir or remove it." -ForegroundColor Red
    exit 1
}

Write-Host "Copying data root -> $Dest ..."
# Exclude volatile/temp noise
$exclude = @("careerpilot.pid", "temp", "cache")
robocopy $DataRoot $Dest /E /XD temp cache /XF careerpilot.pid /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
$code = $LASTEXITCODE
# robocopy 0-7 = success-ish
if ($code -ge 8) {
    Write-Host "ERROR: robocopy failed with code $code" -ForegroundColor Red
    exit 1
}

if (-not $IncludeChrome) {
    $browser = Join-Path $Dest "browser"
    $legacy = Join-Path $Dest "profiles_browser"
    foreach ($b in @($browser, $legacy)) {
        if (Test-Path $b) {
            Remove-Item -Recurse -Force $b
            Write-Host "  Removed browser profiles from export (pass -IncludeChrome to keep)."
        }
    }
}

if ($IncludeBackups -and (Test-Path $BackupsRoot)) {
    $bDest = Join-Path $OutDir "careerpilot_backups"
    Write-Host "Copying backups -> $bDest ..."
    robocopy $BackupsRoot $bDest /E /NFL /NDL /NJH /NJS /nc /ns /np | Out-Null
}

# Manifest
$manifest = @{
    exported_at = (Get-Date).ToUniversalTime().ToString("o")
    source_data_root = $DataRoot
    source_app_root = $AppRoot
    include_chrome = [bool]$IncludeChrome
    include_backups = [bool]$IncludeBackups
} | ConvertTo-Json
Set-Content -Path (Join-Path $Dest "export_manifest.json") -Value $manifest -Encoding UTF8

if ($Compress) {
    $zip = Join-Path $OutDir "careerpilot_data.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path $Dest -DestinationPath $zip -CompressionLevel Optimal
    Write-Host "Compressed -> $zip"
}

Write-Host ""
Write-Host "Export complete." -ForegroundColor Green
Write-Host "  Folder: $Dest"
Write-Host "On the new PC: clone the Git repo into CareerPilot\app\, then run:"
Write-Host "  .\scripts\import_data.ps1 -Source $Dest"
Write-Host "See docs\MIGRATION_GUIDE.md"
exit 0
