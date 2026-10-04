# Start CareerPilot (scheduler + dashboard) from the project folder.
# Uses the virtualenv created by setup_windows.ps1. Does not use a system Python.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$LogErr = Join-Path $LogDir "startup.err.log"
$PidFile = Join-Path $Root "careerpilot.pid"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-StartupError([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $LogErr -Value $line
    Write-Host "ERROR: $Message" -ForegroundColor Red
    Write-Host "Details appended to $LogErr"
}

if (-not (Test-Path $Python)) {
    Write-StartupError ".venv\Scripts\python.exe is missing. Run .\setup_windows.ps1 from $Root first."
    exit 1
}

if (Test-Path $PidFile) {
    $existing = (Get-Content $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($existing -match '^\d+$') {
        $proc = Get-Process -Id ([int]$existing) -ErrorAction SilentlyContinue
        if ($null -ne $proc) {
            Write-Host "CareerPilot is already running (PID $existing). Not starting a second copy." -ForegroundColor Yellow
            exit 0
        }
    }
}

Write-Host "Starting CareerPilot from $Root" -ForegroundColor Cyan
Write-Host "Python: $Python"
Write-Host "Press Ctrl+C to stop. A second start is refused while this one is running."

& $Python -m careerpilot.main run
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-StartupError "CareerPilot exited with code $code. See logs\ for the application log."
    exit $code
}
exit 0
