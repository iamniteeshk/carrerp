"""Runtime hub — bridges CareerPilot live objects into the ops dashboard.

The dashboard never imports Playwright or drives the browser directly. It reads
snapshots written by the worker thread and issues control commands via a queue
that the scheduler/pipeline drain on the safe thread.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ControlCommand:
    action: str
    requested_at: str = field(default_factory=_utcnow)
    detail: str = ""


class RuntimeHub:
    """Singleton-ish registry set once by CareerPilot at startup."""

    def __init__(self):
        self._lock = threading.RLock()
        self.started_at = time.time()
        self.config = None
        self.db = None
        self.scheduler = None
        self.browser = None
        self.ai = None
        self.pipeline = None
        self.diagnostics = None
        self.telegram = None
        self.app = None  # CareerPilot composition root (optional)
        self.paused = False
        self.last_profile_name: str | None = None
        self._commands: deque[ControlCommand] = deque(maxlen=50)
        self._browser_restarts = 0
        self._last_browser_restart = ""
        self._preview_meta: dict[str, Any] = {}
        self._ai_stats = {
            "requests": 0, "success": 0, "failed": 0, "retries": 0,
            "tokens": 0, "latency_sum_ms": 0.0, "cache_hits": 0,
            "cache_misses": 0, "cost_usd": 0.0,
        }

    def bind(self, *, config, db, scheduler=None, browser=None, ai=None,
             pipeline=None, diagnostics=None, telegram=None, app=None) -> None:
        with self._lock:
            self.config = config
            self.db = db
            self.scheduler = scheduler
            self.browser = browser
            self.ai = ai
            self.pipeline = pipeline
            self.diagnostics = diagnostics
            self.telegram = telegram
            self.app = app

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, time.time() - self.started_at)

    def live_status(self) -> dict[str, Any]:
        diag = self.diagnostics
        if diag is None:
            return {}
        try:
            return diag.status.get()
        except Exception:  # noqa: BLE001
            return {}

    def current_phase(self) -> str:
        """Map live status / pause / heartbeat into a coarse ops phase."""
        if self.paused:
            return "Waiting"
        live = self.live_status()
        stage = str(live.get("stage") or "").lower()
        workflow = str(live.get("workflow_state") or "").lower()
        ai = str(live.get("ai_status") or "").lower()
        wait = str(live.get("wait_reason") or "").lower()
        if "error" in stage or "error" in workflow:
            return "Error"
        if "captcha" in wait or "confirm" in wait or "approval" in wait:
            return "Waiting"
        if "apply" in stage or "upload" in stage or "submit" in stage:
            return "Applying"
        if "score" in stage or "gemini" in ai or "evaluat" in ai or "ai" in stage:
            return "Scoring"
        if "search" in stage or "collect" in stage or "scroll" in stage:
            return "Searching"
        hb = Path("logs/health.json")
        if hb.exists():
            try:
                import json
                data = json.loads(hb.read_text(encoding="utf-8"))
                if data.get("status") == "scanning":
                    return "Searching"
                if data.get("status") == "error":
                    return "Error"
            except Exception:  # noqa: BLE001
                pass
        sched = self.scheduler
        if sched is not None and getattr(sched, "is_running", lambda: False)():
            return "Idle"
        return "Idle"

    # ---- controls -------------------------------------------------------

    def enqueue(self, action: str, detail: str = "") -> ControlCommand:
        cmd = ControlCommand(action=action, detail=detail)
        with self._lock:
            self._commands.append(cmd)
        return cmd

    def drain_commands(self) -> list[ControlCommand]:
        with self._lock:
            out = list(self._commands)
            self._commands.clear()
            return out

    def set_paused(self, value: bool) -> None:
        self.paused = bool(value)

    def note_profile(self, name: str | None) -> None:
        with self._lock:
            self.last_profile_name = name or None

    def note_browser_restart(self) -> None:
        with self._lock:
            self._browser_restarts += 1
            self._last_browser_restart = _utcnow()

    def browser_restart_stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "restart_count": self._browser_restarts,
                "last_restart": self._last_browser_restart or None,
            }

    def set_preview(self, *, path: str, url: str = "", title: str = "",
                    portal: str = "", step: str = "") -> None:
        with self._lock:
            self._preview_meta = {
                "path": path, "url": url, "title": title, "portal": portal,
                "step": step, "updated_at": _utcnow(),
            }

    def preview_meta(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._preview_meta)

    def note_ai(self, *, success: bool, tokens: int = 0, latency_ms: float = 0,
                retry: int = 0, cost: float | None = None,
                cache_hit: bool | None = None) -> None:
        with self._lock:
            s = self._ai_stats
            s["requests"] += 1
            if success:
                s["success"] += 1
            else:
                s["failed"] += 1
            s["retries"] += int(retry or 0)
            s["tokens"] += int(tokens or 0)
            s["latency_sum_ms"] += float(latency_ms or 0)
            if cost:
                s["cost_usd"] += float(cost)
            if cache_hit is True:
                s["cache_hits"] += 1
            elif cache_hit is False:
                s["cache_misses"] += 1

    def ai_runtime_stats(self) -> dict[str, Any]:
        with self._lock:
            s = dict(self._ai_stats)
        n = max(1, s["success"])
        s["avg_latency_ms"] = round(s["latency_sum_ms"] / n, 1) if s["success"] else None
        return s


HUB = RuntimeHub()
