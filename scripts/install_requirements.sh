#!/usr/bin/env bash
# One-time setup for macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
