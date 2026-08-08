"""Apply-flow step screenshots for dry-run debugging.

When enabled (config / dashboard toggle), capture a viewport shot after key
apply milestones: open form, resume uploaded, each Next, stop-before-Apply.
"""

from __future__ import annotations

from pathlib import Path
from time import strftime
from typing import Any

from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.browser.apply_evidence")


class ApplyStepEvidence:
    def __init__(self, enabled: bool = False,
                 root: str | Path = "screenshots/apply_steps"):
        self.enabled = bool(enabled)
        self.root = Path(root)
        if self.enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def capture(self, page: Any, job: Any, step: str) -> str:
        if not self.enabled or page is None:
            return ""
        safe_step = "".join(c if c.isalnum() or c in "-_" else "_" for c in step)[:40]
        portal = getattr(job, "portal", "portal") or "portal"
        jid = getattr(job, "job_id", None) or getattr(job, "source_id", None) or "job"
        stamp = strftime("%Y%m%d-%H%M%S")
        folder = self.root / str(portal) / str(jid)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{stamp}_{safe_step}.png"
        try:
            page.screenshot(path=str(path), full_page=False)
            logger.info("Apply-step screenshot | %s | %s", step, path)
            return str(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Apply-step screenshot failed (%s): %s", step, exc)
            return ""
