#!/usr/bin/env bash
# Pull latest code and re-install dependencies. macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v git >/dev/null 2>&1 || { echo "ERROR: git not found." >&2; exit 1; }
echo "Pulling latest..."; git pull --ff-only || { echo "ERROR: git pull failed (uncommitted changes?)." >&2; exit 1; }
python3 -m pip install -r requirements.txt
echo "Updated. Run ./scripts/doctor.sh before starting."
