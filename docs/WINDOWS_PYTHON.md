# Official Windows Python launcher policy for CareerPilot.
#
# Production target: Windows 11 with the `py` launcher.
# Do not rely on the WindowsApps `python` / `python.exe` stubs.
#
# Resolution order (see also careerpilot/core/python_launcher.py):
#   1. .venv\Scripts\python.exe   (after setup_windows.ps1)
#   2. py                         (Windows Python Launcher)
#   3. python3 / python           (fallback; skip WindowsApps when possible)
#   4. sys.executable
#
# Examples:
#   py doctor.py
#   py -m pip install -r requirements.txt
#   py -m playwright install chromium
#   py -m careerpilot.main run
#
# Linux/macOS keep using python3 / .venv/bin/python.
