"""Browser runtime state for lifecycle diagnostics.

When Edge/Chrome crashes unexpectedly, lifecycle hooks need more than a stack
trace -- they need the workflow stage and job being processed. This module is
updated by the browse/evaluate/pipeline layers and read by session hooks.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class BrowserRuntimeState:
    """Thread-safe snapshot of what CareerPilot was doing when a browser event fired."""

    workflow_state: str = "IDLE"
    portal: str = ""
    job_url: str = ""
    job_id: str = ""
    job_title: str = ""
    page_url: str = ""
    updated_at: float = field(default_factory=time.time)

    def set(self, **kwargs) -> None:
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)
            self.updated_at = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "workflow_state": self.workflow_state,
                "portal": self.portal,
                "job_url": self.job_url,
                "job_id": self.job_id,
                "job_title": self.job_title,
                "page_url": self.page_url,
                "updated_at": self.updated_at,
            }

    _lock: threading.Lock = field(default_factory=threading.Lock,
                                  repr=False, compare=False)


# Process-wide singleton read by LifecycleInstrumenter and written by browse code.
RUNTIME = BrowserRuntimeState()
