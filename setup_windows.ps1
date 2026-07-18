#Requires -Version 5.1
<#
.SYNOPSIS
  One-command CareerPilot production setup for a fresh Windows 11 machine
  (e.g. GEEKOM A7 Max).

.DESCRIPTION
  Idempotent. Safe to re-run. Creates a virtualenv, installs Python deps,
  installs Playwright Chromium, scaffolds config/folders, and runs
  ``doctor --fix``.

  Does NOT invent API keys or portal logins — those always require you.

.PARAMETER ProductionConfig
  Prefer config.production.example.yaml when creating config\config.yaml.

.PARAMETER SkipBrowserInstall
  Skip ``playwright install chromium`` (use if already installed).

.PARAMETER PythonExe
  Explicit Python launcher (default: py -3.12 / py -3 / python).

.EXAMPLE
  .\setup_windows.ps1
  .\setup_windows.ps1 -ProductionConfig
#>
[CmdletBinding()]
param(
    [switch]$ProductionConfig,
    [switch]$SkipBrowserInstall,
    [string]$PythonExe = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "  [ OK ] $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "  [WARN] $Message" -ForegroundColor Yellow
}

function Write-Fail([string]$Message) {
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Resolve-Python {
    param([string]$Explicit)
    if ($Explicit -and (Test-Path $Explicit)) { return $Explicit }
    if ($Explicit -and (Test-Command $Explicit)) { return $Explicit }

    # Prefer the Python launcher for 3.10+.
    if (Test-Command "py") {
        foreach ($ver in @("-3.12", "-3.11", "-3.10", "-3")) {
            try {
                $out = & py $ver -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
            } catch { }
        }
    }
    if (Test-Command "python") {
        try {
            $out = & python -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
        } catch { }
    }
    if (Test-Command "python3") {
        try {
            $out = & python3 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
        } catch { }
    }
    return $null
}

# ---- move to repo root (script may live at root or under scripts/) ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path (Join-Path $ScriptDir "careerpilot")) {
    Set-Location $ScriptDir
} elseif (Test-Path (Join-Path $ScriptDir "..\careerpilot")) {
    Set-Location (Join-Path $ScriptDir "..")
} else {
    Write-Fail "Cannot locate CareerPilot repo root (careerpilot/ package missing)."
    Write-Host "Clone the repo, then run setup_windows.ps1 from the repo root."
    exit 1
}
$Root = (Get-Location).Path
Write-Host "CareerPilot Windows setup" -ForegroundColor White
Write-Host "Root: $Root"

# ---- 1. Git ----
Write-Step "Checking Git"
if (Test-Command "git") {
    Write-Ok ("git " + (git --version))
} else {
    Write-Warn "Git not found on PATH. Install from https://git-scm.com/download/win"
    Write-Warn "Setup can continue, but updates via 'git pull' will not work."
}

# ---- 2. Python ----
Write-Step "Checking Python 3.10+"
$py = Resolve-Python -Explicit $PythonExe
if (-not $py) {
    Write-Fail "Python 3.10+ not found."
    Write-Host ""
    Write-Host "Install Python from https://www.python.org/downloads/windows/"
    Write-Host "  - Check 'Add python.exe to PATH'"
    Write-Host "  - Check 'Install py launcher'"
    Write-Host "Then re-run: .\setup_windows.ps1"
    exit 1
}
$verLine = & $py -c "import sys; print('%d.%d.%d' % sys.version_info[:3]); raise SystemExit(0 if sys.version_info >= (3,10) else 2)"
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Python $verLine is too old. CareerPilot needs 3.10+."
    exit 1
}
Write-Ok "Python $verLine at $py"

# ---- 3. Virtual environment ----
Write-Step "Creating / verifying .venv"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    & $py -m venv .venv
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) {
        Write-Fail "Failed to create .venv"
        exit 1
    }
    Write-Ok "Created .venv"
} else {
    Write-Ok ".venv already exists"
}
$VenvPython = $venvPy
$VenvPip = Join-Path $Root ".venv\Scripts\pip.exe"

# ---- 4. pip + requirements ----
Write-Step "Installing Python packages"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Fail "pip upgrade failed"; exit 1 }
& $VenvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install -r requirements.txt failed"
    Write-Host "Check your internet connection and re-run setup_windows.ps1"
    exit 1
}
Write-Ok "requirements.txt installed"

# ---- 5. Playwright browsers ----
if (-not $SkipBrowserInstall) {
    Write-Step "Installing Playwright Chromium"
    & $VenvPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "playwright install chromium failed"
        Write-Host "Re-run later: .\.venv\Scripts\python.exe -m playwright install chromium"
        exit 1
    }
    Write-Ok "Playwright Chromium installed"
} else {
    Write-Warn "Skipped Playwright browser install (-SkipBrowserInstall)"
}

# ---- 6. System Chrome (recommended for production channel: chrome) ----
Write-Step "Checking Google Chrome"
$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chrome) {
    Write-Ok "Chrome found: $chrome"
} else {
    Write-Warn "Google Chrome not found."
    Write-Warn "Install from https://www.google.com/chrome/ OR set browser.channel: `"`" in config to use bundled Chromium."
}

# ---- 7. Scaffold + doctor --fix ----
Write-Step "Scaffolding config, profiles, folders, database"
$doctorArgs = @("-m", "careerpilot.main", "doctor", "--fix")
if ($ProductionConfig) { $doctorArgs += "--production" }
& $VenvPython @doctorArgs
$doctorExit = $LASTEXITCODE

# ---- 8. Summary ----
Write-Host ""
Write-Host "============================================================" -ForegroundColor White
Write-Host " Setup finished" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor White
Write-Host "Next steps (manual — secrets & logins cannot be automated):"
Write-Host "  1. Edit .env               -> set GEMINI_API_KEY_1=..."
Write-Host "  2. Edit .env               -> set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (optional)"
Write-Host "  3. Edit config\config.yaml -> candidate details, blacklist, locations"
Write-Host "  4. Copy resume.pdf into each profiles\<Name>\ folder"
Write-Host "  5. Re-run doctor:   .\.venv\Scripts\python.exe -m careerpilot.main doctor"
Write-Host "  6. First login:     .\.venv\Scripts\python.exe -m careerpilot.main scan"
Write-Host "     (headed Chrome opens — log into LinkedIn + Naukri once)"
Write-Host "  7. Start 24x7:      .\.venv\Scripts\python.exe -m careerpilot.main run"
Write-Host "                      or scripts\run_careerpilot.ps1"
Write-Host ""
Write-Host "Docs: docs\INSTALL_WINDOWS.md"
Write-Host "============================================================"

if ($doctorExit -ne 0) {
    Write-Warn "Doctor reported mandatory failures (usually missing API keys / resumes)."
    Write-Warn "Complete the Next steps above, then re-run doctor until PASS."
    exit $doctorExit
}
Write-Ok "Doctor PASS — complete Next steps for keys/logins, then start with 'run'."
exit 0
