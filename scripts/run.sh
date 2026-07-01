#!/usr/bin/env bash
# Start CareerPilot (foreground). macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 not found." >&2; exit 1; }
[ -f config/config.yaml ] || { echo "ERROR: config/config.yaml missing." >&2; exit 1; }
if [ -f careerpilot.pid ] && kill -0 "$(cat careerpilot.pid)" 2>/dev/null; then
  echo "ERROR: CareerPilot already running (PID $(cat careerpilot.pid)). Use ./scripts/stop.sh first." >&2; exit 1
fi
exec python3 -m careerpilot.main run
