"""Best-effort Windows Event Log integration.

No extra packages required. On Windows, events are written via PowerShell
``Write-EventLog`` after ensuring the ``CareerPilot`` source exists (needs
Administrator once). On other OSes this is a no-op that still logs to the
application logger.

Event IDs (Application log):
  1000  startup
  1001  shutdown
  1002  browser crash / restart
  1003  AI unavailable
  1004  scheduler stopped / scan crash
  1005  fatal exception
  1006  recovery / restart triggered
"""

from __future__ import annotations

import subprocess
import sys
from enum import Enum

from .logging_setup import get_logger

logger = get_logger(__name__)

_SOURCE = "CareerPilot"
_LOG = "Application"
_SOURCE_READY: bool | None = None


class EventKind(str, Enum):
    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    BROWSER = "browser"
    AI = "ai"
    SCHEDULER = "scheduler"
    FATAL = "fatal"
    RECOVERY = "recovery"


_EVENT_IDS = {
    EventKind.STARTUP: 1000,
    EventKind.SHUTDOWN: 1001,
    EventKind.BROWSER: 1002,
    EventKind.AI: 1003,
    EventKind.SCHEDULER: 1004,
    EventKind.FATAL: 1005,
    EventKind.RECOVERY: 1006,
}

_ENTRY_TYPES = {
    EventKind.STARTUP: "Information",
    EventKind.SHUTDOWN: "Information",
    EventKind.BROWSER: "Warning",
    EventKind.AI: "Warning",
    EventKind.SCHEDULER: "Error",
    EventKind.FATAL: "Error",
    EventKind.RECOVERY: "Warning",
}


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def ensure_event_source() -> bool:
    """Create the CareerPilot event source if missing. May need Admin once."""
    global _SOURCE_READY
    if not _is_windows():
        _SOURCE_READY = False
        return False
    if _SOURCE_READY is not None:
        return _SOURCE_READY
    ps = (
        f"if (-not [System.Diagnostics.EventLog]::SourceExists('{_SOURCE}')) {{ "
        f"try {{ New-EventLog -LogName {_LOG} -Source '{_SOURCE}'; $true }} "
        f"catch {{ $false }} }} else {{ $true }}"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=15)
        _SOURCE_READY = r.returncode == 0 and "True" in (r.stdout or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Event source setup skipped: %s", exc)
        _SOURCE_READY = False
    return bool(_SOURCE_READY)


def write_event(kind: EventKind | str, message: str) -> bool:
    """Write one Windows Event Log entry. Never raises. Returns True if written."""
    try:
        kind_e = kind if isinstance(kind, EventKind) else EventKind(str(kind))
    except ValueError:
        kind_e = EventKind.FATAL
    # Always mirror to application logs.
    level = logger.error if kind_e in (EventKind.FATAL, EventKind.SCHEDULER) else (
        logger.warning if kind_e in (EventKind.BROWSER, EventKind.AI, EventKind.RECOVERY)
        else logger.info)
    level("[event] %s | %s", kind_e.value, message)

    if not _is_windows():
        return False
    if not ensure_event_source():
        return False
    eid = _EVENT_IDS[kind_e]
    etype = _ENTRY_TYPES[kind_e]
    # Escape for PowerShell single-quoted string.
    safe = (message or "").replace("'", "''")[:3000]
    ps = (
        f"Write-EventLog -LogName {_LOG} -Source '{_SOURCE}' "
        f"-EventId {eid} -EntryType {etype} -Message '{safe}'"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except Exception as exc:  # noqa: BLE001
        logger.debug("Write-EventLog failed: %s", exc)
        return False
