#!/usr/bin/env bash
# Install dependencies and the browser. macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found. Install Python 3.10+." >&2; exit 1; }
echo "Installing Python dependencies..."
python3 -m pip install -r requirements.txt || { echo "ERROR: pip install failed." >&2; exit 1; }
echo "Installing the configured browser (Playwright)..."
python3 -m playwright install chromium || { echo "ERROR: playwright browser install failed." >&2; exit 1; }
echo "Done. Next: edit the blank .env ; python3 -m careerpilot.main setup ; ./scripts/doctor.sh"
