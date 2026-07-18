#Requires -Version 5.1
<#
.SYNOPSIS
  One-command CareerPilot production setup for a fresh Windows 11 machine
  (e.g. GEEKOM A7 Max).

.DESCRIPTION
  Idempotent. Safe to re-run. Uses the Windows ``py`` launcher (not the
  unreliable WindowsApps ``python`` stub) to create a virtualenv, install
  deps via ``py -m pip`` / venv ``-m pip``, install Playwright Chromium,
  scaffold config/folders, and run ``doctor --fix``.

  Does NOT invent API keys or portal logins — those always require you.

.PARAMETER ProductionConfig
  Prefer config.production.example.yaml when creating config\config.yaml.

.PARAMETER SkipBrowserInstall
  Skip ``playwright install chromium`` (use if already installed).

.PARAMETER PythonExe
  Explicit host interpreter/launcher (default: py → python3 → python).

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
function Test-Cmd([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Resolve-HostPython {
    param([string]$Explicit)
    if ($Explicit) {
        if (Test-Path $Explicit) { return $Explicit }
        if (Test-Cmd $Explicit) { return $Explicit }
    }
    # Official Windows path: py launcher (never prefer WindowsApps python).
    if (Test-Cmd "py") { return "py" }
    if (Test-Cmd "python3") { return "python3" }
    if (Test-Cmd "python") {
        $src = (Get-Command python).Source
        if ($src -and ($src -notmatch "WindowsApps")) { return "python" }
        Write-Warn "Found WindowsApps python stub — prefer installing the py launcher."
        return "python"
    }
    return $null
}

function Invoke-HostPython {
    param([string]$Launcher, [string[]]$Args)
    if ($Launcher -eq "py") {
        # Prefer a concrete 3.10+ runtime when the launcher supports it.
        foreach ($ver in @("-3.12", "-3.11", "-3.10", "-3")) {
            & py $ver @Args
            if ($LASTEXITCODE -ne 9009) { return $LASTEXITCODE }
        }
        & py @Args
        return $LASTEXITCODE
    }
    & $Launcher @Args
    return $LASTEXITCODE
}

# ---- move to repo root ----
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path (Join-Path $ScriptDir "careerpilot")) {
    Set-Location $ScriptDir
} elseif (Test-Path (Join-Path $ScriptDir "..\careerpilot")) {
    Set-Location (Join-Path $ScriptDir "..")
} else {
    Write-Fail "Cannot locate CareerPilot repo root (careerpilot/ package missing)."
    exit 1
}
$Root = (Get-Location).Path
Write-Host "CareerPilot Windows setup" -ForegroundColor White
Write-Host "Root: $Root"
Write-Host "Launcher policy: py → python3 → python (venv preferred after create)"

# Production layout: when repo lives in ...\CareerPilot\app, use sibling data\.
$leaf = Split-Path $Root -Leaf
if ($leaf -eq "app") {
    $HomeDir = Split-Path $Root -Parent
    if (-not $env:CAREERPILOT_HOME) {
        $env:CAREERPILOT_HOME = $HomeDir
        Write-Ok "CAREERPILOT_HOME=$HomeDir (session)"
    }
    $dataDir = Join-Path $HomeDir "data"
    $backupsDir = Join-Path $HomeDir "backups"
    New-Item -ItemType Directory -Force -Path $dataDir, $backupsDir | Out-Null
    if (-not $env:CAREERPILOT_DATA_ROOT) {
        $env:CAREERPILOT_DATA_ROOT = $dataDir
    }
    Write-Ok "data root = $dataDir"
} elseif ($env:CAREERPILOT_HOME) {
    Write-Ok "CAREERPILOT_HOME=$($env:CAREERPILOT_HOME)"
} else {
    Write-Warn "Repo not in ...\app — using legacy in-repo data dirs (gitignored)."
    Write-Warn "For production: clone into C:\CareerPilot\app and set CAREERPILOT_HOME."
}

# ---- 1. Git ----
Write-Step "Checking Git"
if (Test-Cmd "git") {
    Write-Ok ("git " + (git --version))
} else {
    Write-Warn "Git not found on PATH. Install from https://git-scm.com/download/win"
}

# ---- 2. Python (py launcher) ----
Write-Step "Checking Python via py launcher (3.10+)"
$hostPy = Resolve-HostPython -Explicit $PythonExe
if (-not $hostPy) {
    Write-Fail "No Python launcher found."
    Write-Host ""
    Write-Host "Install Python 3.12 from https://www.python.org/downloads/windows/"
    Write-Host "  - Enable 'Install launcher for all users' (py.exe)"
    Write-Host "  - 'Add python.exe to PATH' is optional; CareerPilot prefers py"
    Write-Host "Then re-run: .\setup_windows.ps1"
    exit 1
}
$verExit = Invoke-HostPython -Launcher $hostPy -Args @(
    "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3]); raise SystemExit(0 if sys.version_info >= (3,10) else 2)"
)
# Capture version text from last successful py -3.x if needed
$verLine = & {
    if ($hostPy -eq "py") {
        foreach ($ver in @("-3.12", "-3.11", "-3.10", "-3")) {
            $o = & py $ver -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $o) { return $o.Trim() }
        }
    }
    $o = & $hostPy -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
    if ($o) { return $o.Trim() }
    return "?"
}
if ($verExit -ne 0 -and $verLine -ne "?") {
    # re-check version gate
    $gate = 0
    if ($hostPy -eq "py") {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)"
        $gate = $LASTEXITCODE
    } else {
        & $hostPy -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 2)"
        $gate = $LASTEXITCODE
    }
    if ($gate -ne 0) {
        Write-Fail "Python $verLine is too old. CareerPilot needs 3.10+."
        exit 1
    }
}
Write-Ok "Python $verLine via launcher '$hostPy'"

# ---- 3. Virtual environment ----
Write-Step "Creating / verifying .venv"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    $null = Invoke-HostPython -Launcher $hostPy -Args @("-m", "venv", ".venv")
    if (-not (Test-Path $venvPy)) {
        Write-Fail "Failed to create .venv"
        exit 1
    }
    Write-Ok "Created .venv"
} else {
    Write-Ok ".venv already exists"
}
$VenvPython = $venvPy

# ---- 4. pip + requirements (always -m pip, never bare pip.exe) ----
Write-Step "Installing Python packages (py/venv -m pip)"
& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Fail "pip upgrade failed"; exit 1 }
& $VenvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Fail "pip install -r requirements.txt failed"
    exit 1
}
Write-Ok "requirements.txt installed"

# ---- 5. Playwright ----
if (-not $SkipBrowserInstall) {
    Write-Step "Installing Playwright Chromium"
    & $VenvPython -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "playwright install chromium failed"
        Write-Host "Re-run later: py -m playwright install chromium"
        Write-Host "  (or) .\.venv\Scripts\python.exe -m playwright install chromium"
        exit 1
    }
    Write-Ok "Playwright Chromium installed"
} else {
    Write-Warn "Skipped Playwright browser install (-SkipBrowserInstall)"
}

# ---- 6. Chrome ----
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
    Write-Warn "Install from https://www.google.com/chrome/ OR set browser.channel: `"`" for bundled Chromium."
}

# ---- 7. doctor --fix ----
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
Write-Host "Windows commands use the py launcher (or .venv after setup):"
if ($env:CAREERPILOT_DATA_ROOT) {
    Write-Host "  Data root: $($env:CAREERPILOT_DATA_ROOT)"
    Write-Host "  1. Edit data\.env               -> GEMINI_API_KEY_1=..."
    Write-Host "  2. Edit data\config\config.yaml -> candidate details"
    Write-Host "  3. Copy resume.pdf into data\profiles\<Name>\"
} else {
    Write-Host "  1. Edit .env               -> GEMINI_API_KEY_1=..."
    Write-Host "  2. Edit config\config.yaml -> candidate details"
    Write-Host "  3. Copy resume.pdf into profiles\<Name>\"
}
Write-Host "  4. Re-run doctor:   py -m careerpilot.main doctor"
Write-Host "  5. First login:     py -m careerpilot.main scan"
Write-Host "  6. Start 24x7:      py -m careerpilot.main run"
Write-Host "  7. Register startup: .\scripts\Register-CareerPilotStartup.ps1"
Write-Host ""
Write-Host "Docs: docs\DATA_STRUCTURE.md  docs\INSTALL_WINDOWS.md"
Write-Host "============================================================"

if ($doctorExit -ne 0) {
    Write-Warn "Doctor reported mandatory failures (usually missing API keys / resumes)."
    exit $doctorExit
}
Write-Ok "Doctor PASS — complete Next steps for keys/logins, then start with 'run'."
exit 0
