#Requires -Version 5.1
<#
.SYNOPSIS
  Safe CareerPilot update: pull, preserve user data, reinstall deps, doctor.

.DESCRIPTION
  Never overwrites config\config.yaml, .env, profiles\, profiles_browser\,
  database\, reports\, or logs\. Aborts if doctor reports mandatory failures.

.EXAMPLE
  .\scripts\update_careerpilot.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipGitPull,
    [switch]$AllowDoctorWarnings
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Set-Location (Join-Path $PSScriptRoot "..")
$Root = (Get-Location).Path

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m) { Write-Host "  [ OK ] $m" -ForegroundColor Green }
function Write-Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Fail ".venv missing. Run .\setup_windows.ps1 first."
    exit 1
}

# Refuse to run while CareerPilot is live (protect DB / profiles).
if (Test-Path "careerpilot.pid") {
    $pidText = (Get-Content "careerpilot.pid" -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($pidText) {
        $running = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if ($running) {
            Write-Fail "CareerPilot is running (PID $pidText). Stop it first:"
            Write-Host "  .\scripts\stop_careerpilot.bat"
            exit 2
        }
    }
}

Write-Step "Preserving user data (config, .env, profiles, DB, Chrome profiles, reports, logs)"
$preserve = @(
    "config\config.yaml", ".env", "profiles", "profiles_browser",
    "database", "reports", "logs", "screenshots", "cache", "documents"
)
foreach ($p in $preserve) {
    if (Test-Path $p) { Write-Ok "kept $p" } else { Write-Host "  [ -- ] $p (not present)" }
}

if (-not $SkipGitPull) {
    Write-Step "git pull --ff-only"
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Fail "git not found on PATH"
        exit 1
    }
    # Stash only tracked code changes; never touch ignored user files.
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "git pull failed (uncommitted tracked changes or network). Aborting."
        Write-Host "Your config/.env/database/profiles were NOT modified."
        exit 1
    }
    Write-Ok "code updated"
} else {
    Write-Host "  skipped git pull"
}

Write-Step "Updating Python packages from requirements.txt / requirements.lock"
if (Test-Path "requirements.lock") {
    & $py -m pip install -r requirements.lock
} else {
    & $py -m pip install -r requirements.txt
}
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install failed"
    exit 1
}
Write-Ok "packages installed"

Write-Step "Playwright Chromium (idempotent)"
& $py -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Fail "playwright install failed"
    exit 1
}
Write-Ok "browser binary ready"

Write-Step "Database migrations (initialize is idempotent)"
& $py -m careerpilot.main check
if ($LASTEXITCODE -ne 0) {
    Write-Fail "database/config check failed"
    exit 1
}
Write-Ok "schema OK"

Write-Step "doctor --fix"
& $py -m careerpilot.main doctor --fix
$docExit = $LASTEXITCODE
if ($docExit -ne 0) {
    Write-Fail "Doctor reported mandatory failures. Update aborted (app not started)."
    Write-Host "Fix the issues above, then re-run update_careerpilot.ps1"
    exit $docExit
}
Write-Ok "Doctor PASS"

Write-Host ""
Write-Host "Update complete. Start with: .\scripts\run_careerpilot.ps1" -ForegroundColor Green
exit 0
