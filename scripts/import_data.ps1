#Requires -Version 5.1
<#
.SYNOPSIS
  Import CareerPilot user data from an export_data.ps1 package.

.DESCRIPTION
  Restores config, .env, profiles, database, documents, certificates, and
  optionally browser sessions into the local data root. Does NOT touch the
  Git application tree.

.PARAMETER Source
  Path to careerpilot_data folder OR careerpilot_data.zip from export_data.ps1.

.PARAMETER Force
  Overwrite existing files in the data root.

.PARAMETER IncludeChrome
  Restore browser/ profiles when present in the export.

.EXAMPLE
  .\scripts\import_data.ps1 -Source D:\migrate\careerpilot_data -Force
  .\scripts\import_data.ps1 -Source D:\migrate\careerpilot_data.zip -Force -IncludeChrome
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Source,

    [switch]$Force,
    [switch]$IncludeChrome
)

$ErrorActionPreference = "Stop"
$AppRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $AppRoot

if ($env:CAREERPILOT_DATA_ROOT) {
    $DataRoot = $env:CAREERPILOT_DATA_ROOT
} elseif ($env:CAREERPILOT_HOME) {
    $DataRoot = Join-Path $env:CAREERPILOT_HOME "data"
} elseif ((Split-Path $AppRoot -Leaf) -eq "app") {
    $DataRoot = Join-Path (Split-Path $AppRoot -Parent) "data"
} elseif (Test-Path (Join-Path $AppRoot "data")) {
    $DataRoot = Join-Path $AppRoot "data"
} else {
    # Prefer creating sibling data when under ...\CareerPilot\app
    if ((Split-Path $AppRoot -Leaf) -eq "app") {
        $DataRoot = Join-Path (Split-Path $AppRoot -Parent) "data"
    } else {
        $DataRoot = Join-Path $AppRoot "data"
    }
}

Write-Host "App root:  $AppRoot"
Write-Host "Data root: $DataRoot"

$Src = $Source
$tempExtract = $null
if ($Source -match "\.zip$") {
    if (-not (Test-Path $Source)) {
        Write-Host "ERROR: zip not found: $Source" -ForegroundColor Red
        exit 1
    }
    $tempExtract = Join-Path $env:TEMP ("cp_import_" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $tempExtract | Out-Null
    Expand-Archive -Path $Source -DestinationPath $tempExtract -Force
    $candidate = Join-Path $tempExtract "careerpilot_data"
    if (Test-Path $candidate) {
        $Src = $candidate
    } else {
        # Zip may contain contents at top level
        $Src = $tempExtract
    }
}

if (-not (Test-Path $Src)) {
    Write-Host "ERROR: source not found: $Src" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

$items = @(
    "config",
    ".env",
    "profiles",
    "documents",
    "certificates",
    "database",
    "logs",
    "reports",
    "screenshots",
    "debug",
    "health",
    "exports"
)
if ($IncludeChrome) {
    $items += @("browser", "profiles_browser")
}

foreach ($name in $items) {
    $from = Join-Path $Src $name
    if (-not (Test-Path $from)) { continue }
    $to = Join-Path $DataRoot $name
    if ((Test-Path $to) -and -not $Force) {
        Write-Host "  SKIP $name (exists; pass -Force to overwrite)"
        continue
    }
    if (Test-Path $to) {
        Remove-Item -Recurse -Force $to
    }
    if (Test-Path $from -PathType Container) {
        Copy-Item -Recurse -Force $from $to
    } else {
        Copy-Item -Force $from $to
    }
    Write-Host "  RESTORED $name"
}

# Ensure standard empty dirs exist
& {
    . (Join-Path $PSScriptRoot "_ResolvePython.ps1")
    $py = Get-CareerPilotPython
    if ($py) {
        if ($py -eq "py") {
            $env:CAREERPILOT_DATA_ROOT = $DataRoot
            & py -m careerpilot.main setup | Out-Null
        } else {
            $env:CAREERPILOT_DATA_ROOT = $DataRoot
            & $py -m careerpilot.main setup | Out-Null
        }
    }
}

Write-Host ""
Write-Host "Import complete into $DataRoot" -ForegroundColor Green
Write-Host "Next:"
Write-Host "  `$env:CAREERPILOT_HOME = '$((Split-Path $DataRoot -Parent))'   # if using C:\CareerPilot"
Write-Host "  py -m careerpilot.main doctor"
Write-Host "See docs\MIGRATION_GUIDE.md"

if ($tempExtract) {
    Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
}
exit 0
