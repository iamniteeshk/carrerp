#!/usr/bin/env bash
# Restart CareerPilot. macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/stop.sh || true
sleep 1
nohup ./scripts/run.sh > logs/run.out 2>&1 &
echo "Restarted (background). Logs: logs/run.out"
