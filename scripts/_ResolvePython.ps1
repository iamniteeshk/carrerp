# Shared Python resolver for CareerPilot Windows PowerShell scripts.
# Dot-source from repo scripts:
#   . (Join-Path $PSScriptRoot "_ResolvePython.ps1")
#   $py = Get-CareerPilotPython
#
# Order: .venv\Scripts\python.exe → py → python3 → python
# Never rely on the WindowsApps "python" stub alone.

function Test-CareerPilotCommand([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-CareerPilotPython {
    param(
        [string]$Root = (Get-Location).Path,
        [switch]$HostOnly   # skip venv (for creating the venv itself)
    )

    if (-not $HostOnly) {
        $venvPy = Join-Path $Root ".venv\Scripts\python.exe"
        if (Test-Path $venvPy) {
            return (Resolve-Path $venvPy).Path
        }
    }

    if (Test-CareerPilotCommand "py") {
        foreach ($ver in @("-3.12", "-3.11", "-3.10", "-3")) {
            try {
                $out = & py $ver -c "import sys; print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $out) {
                    # Prefer invoking via py launcher for host commands;
                    # for resolved absolute path use the printed executable.
                    if ($HostOnly) { return "py" }
                    return $out.Trim()
                }
            } catch { }
        }
        return "py"
    }

    if (Test-CareerPilotCommand "python3") { return "python3" }

    if (Test-CareerPilotCommand "python") {
        try {
            $where = (Get-Command python).Source
            if ($where -and ($where -notmatch "WindowsApps")) {
                return "python"
            }
        } catch { }
        # WindowsApps stub — last resort only
        return "python"
    }

    return $null
}

function Invoke-CareerPilotPython {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments,
        [string]$Root = (Get-Location).Path
    )
    $py = Get-CareerPilotPython -Root $Root
    if (-not $py) {
        throw "No Python launcher found. Install Python with the py launcher, then run setup_windows.ps1."
    }
    if ($py -eq "py") {
        & py @Arguments
    } else {
        & $py @Arguments
    }
    return $LASTEXITCODE
}
