#!/usr/bin/env bash
# Stop a running CareerPilot. macOS / Linux.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f careerpilot.pid ]; then echo "Not running (no careerpilot.pid)."; exit 0; fi
PID="$(cat careerpilot.pid)"
if ! kill -0 "$PID" 2>/dev/null; then echo "Process $PID not running; cleaning up."; rm -f careerpilot.pid; exit 0; fi
echo "Stopping CareerPilot (PID $PID)..."
kill -TERM "$PID"
for i in $(seq 1 15); do kill -0 "$PID" 2>/dev/null || { echo "Stopped."; rm -f careerpilot.pid; exit 0; }; sleep 1; done
echo "Did not stop gracefully; forcing." >&2; kill -KILL "$PID" 2>/dev/null || true; rm -f careerpilot.pid
