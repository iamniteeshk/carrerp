#!/usr/bin/env bash
# Pre-flight validation. macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found." >&2; exit 1; }
[ -f config/config.yaml ] || { echo "ERROR: config/config.yaml missing. Copy config.example.yaml to it." >&2; exit 1; }
[ -f .env ] || echo "WARNING: .env missing; copy .env.example to .env and add your keys."
python3 -m careerpilot.main doctor
