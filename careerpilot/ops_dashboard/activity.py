"""In-memory activity / notification ring buffers for the live feed.

Writers (pipeline, browser recovery, AI, scheduler) push events; the dashboard
and WebSocket consumers read them. Important events are also mirrored to the
``activity_events`` table when a Database handle is available.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ActivityEvent:
    ts: str
    level: str  # info | success | warn | error | alert
    category: str  # scan | ai | browser | apply | scheduler | system | notify
    message: str
    detail: str = ""
    job_id: int | None = None
    portal: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActivityFeed:
    def __init__(self, maxlen: int = 2000):
        self._lock = threading.Lock()
        self._events: deque[ActivityEvent] = deque(maxlen=maxlen)
        self._alerts: deque[ActivityEvent] = deque(maxlen=200)
        self._seq = 0
        self._listeners: list[Callable[[ActivityEvent], None]] = []
        self._db = None  # optional Database

    def bind_db(self, db) -> None:
        self._db = db

    def subscribe(self, fn: Callable[[ActivityEvent], None]) -> None:
        with self._lock:
            self._listeners.append(fn)

    def push(self, message: str, *, level: str = "info", category: str = "system",
             detail: str = "", job_id: int | None = None, portal: str = "") -> ActivityEvent:
        ev = ActivityEvent(
            ts=_utcnow(), level=level, category=category, message=message,
            detail=detail, job_id=job_id, portal=portal)
        with self._lock:
            self._seq += 1
            self._events.appendleft(ev)
            if level in ("error", "alert", "warn"):
                self._alerts.appendleft(ev)
            listeners = list(self._listeners)
        for fn in listeners:
            try:
                fn(ev)
            except Exception:  # noqa: BLE001
                pass
        self._persist(ev)
        return ev

    def recent(self, limit: int = 100, after_ts: str = "") -> list[dict]:
        with self._lock:
            items = list(self._events)
        if after_ts:
            items = [e for e in items if e.ts > after_ts]
        return [e.as_dict() for e in items[:limit]]

    def alerts(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [e.as_dict() for e in list(self._alerts)[:limit]]

    def _persist(self, ev: ActivityEvent) -> None:
        db = self._db
        if db is None:
            return
        try:
            conn = db.connect()
            conn.execute(
                "INSERT INTO activity_events "
                "(ts, level, category, message, detail, job_id, portal) "
                "VALUES (?,?,?,?,?,?,?)",
                (ev.ts, ev.level, ev.category, ev.message, ev.detail,
                 ev.job_id, ev.portal))
            conn.commit()
        except Exception:  # noqa: BLE001
            pass


# Process-wide feed shared by engine writers and the dashboard.
FEED = ActivityFeed()


def emit(message: str, **kwargs) -> ActivityEvent:
    return FEED.push(message, **kwargs)
