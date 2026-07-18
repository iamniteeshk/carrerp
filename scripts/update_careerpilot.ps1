#Requires -Version 5.1
<#
.SYNOPSIS
  Safe CareerPilot update: pull, preserve user data, reinstall deps, doctor.

.DESCRIPTION
  Never overwrites config\config.yaml, .env, profiles\, profiles_browser\,
  database\, reports\, or logs\. Aborts if doctor reports mandatory failures.
  Uses .venv interpreter when present, otherwise the py launcher.

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
. (Join-Path $PSScriptRoot "_ResolvePython.ps1")

function Write-Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Write-Ok($m) { Write-Host "  [ OK ] $m" -ForegroundColor Green }
function Write-Fail($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

$py = Get-CareerPilotPython -Root $Root
if (-not $py) {
    Write-Fail "No Python launcher / .venv. Run .\setup_windows.ps1 first."
    exit 1
}

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

function Invoke-Py([string[]]$Args) {
    if ($py -eq "py") { & py @Args } else { & $py @Args }
    return $LASTEXITCODE
}

Write-Step "Updating Python packages (launcher -m pip)"
$req = if (Test-Path "requirements.lock") { "requirements.lock" } else { "requirements.txt" }
$code = Invoke-Py @("-m", "pip", "install", "-r", $req)
if ($code -ne 0) { Write-Fail "pip install failed"; exit 1 }
Write-Ok "packages installed"

Write-Step "Playwright Chromium (idempotent)"
$code = Invoke-Py @("-m", "playwright", "install", "chromium")
if ($code -ne 0) { Write-Fail "playwright install failed"; exit 1 }
Write-Ok "browser binary ready"

Write-Step "Database migrations (initialize is idempotent)"
$code = Invoke-Py @("-m", "careerpilot.main", "check")
if ($code -ne 0) { Write-Fail "database/config check failed"; exit 1 }
Write-Ok "schema OK"

Write-Step "doctor --fix"
$code = Invoke-Py @("-m", "careerpilot.main", "doctor", "--fix")
if ($code -ne 0) {
    Write-Fail "Doctor reported mandatory failures. Update aborted (app not started)."
    Write-Host "Fix the issues above, then re-run update_careerpilot.ps1"
    exit $code
}
Write-Ok "Doctor PASS"

Write-Host ""
Write-Host "Update complete. Start with: .\scripts\run_careerpilot.ps1" -ForegroundColor Green
Write-Host "  or: py -m careerpilot.main run"
exit 0
