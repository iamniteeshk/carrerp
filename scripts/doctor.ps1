# Run CareerPilot pre-flight checks from PowerShell.
Set-Location (Join-Path $PSScriptRoot "..")
if (Test-Path ".venv\Scripts\Activate.ps1") { . ".venv\Scripts\Activate.ps1" }
python -m careerpilot.main doctor
