"""Human Interaction Engine.

When the workflow hits something only a human can clear -- CAPTCHA, OTP, MFA,
login approval -- this module captures the exact situation (screenshot + HTML +
state) so you can act, and so the workflow can later resume from the same point
rather than restarting. It NEVER solves the challenge itself.

It is deliberately dependency-light: it takes a Playwright ``page`` (or anything
with ``screenshot`` / ``content`` / ``url``) and an optional ``notify`` callback,
so it stays decoupled from Telegram, the browser engine, and the scheduler.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import strftime
from typing import Any, Callable

from .logging_setup import get_logger
from .state import WorkflowState

logger = get_logger(__name__)

# Maps a pause kind to the explicit waiting state it should hold.
KIND_TO_STATE = {
    "login": WorkflowState.WAITING_FOR_LOGIN,
    "otp": WorkflowState.WAITING_FOR_OTP,
    "captcha": WorkflowState.WAITING_FOR_CAPTCHA,
    "user": WorkflowState.WAITING_FOR_USER,
}


@dataclass
class InteractionBundle:
    kind: str
    state: WorkflowState
    reason: str
    url: str
    screenshot_path: str
    html_path: str
    meta_path: str


class HumanInteractionEngine:
    def __init__(self, diagnostics_dir: str | Path = "screenshots",
                 notify: Callable[[str], None] | None = None):
        self.dir = Path(diagnostics_dir)
        self.notify = notify

    def pause(self, page: Any, kind: str, reason: str,
              portal: str = "") -> InteractionBundle:
        """Capture the current situation and notify. Returns the saved bundle.

        Capture failures are tolerated (we never crash the workflow just because
        a screenshot could not be written).
        """
        state = KIND_TO_STATE.get(kind, WorkflowState.WAITING_FOR_USER)
        stamp = strftime("%Y%m%d-%H%M%S")
        base = self.dir / f"{portal or 'session'}-{kind}-{stamp}"
        self.dir.mkdir(parents=True, exist_ok=True)

        url = _safe(lambda: page.url, "")
        shot = self._screenshot(page, f"{base}.png")
        html = self._html(page, f"{base}.html")
        meta_path = f"{base}.json"
        try:
            Path(meta_path).write_text(json.dumps({
                "kind": kind, "state": state.value, "reason": reason,
                "portal": portal, "url": url, "time": stamp,
            }, indent=2))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not write interaction meta: %s", exc)
            meta_path = ""

        logger.warning("HUMAN ACTION NEEDED | portal=%s | kind=%s | state=%s | "
                       "url=%s | reason=%s | saved=%s",
                       portal, kind, state.value, url, reason, base)
        if self.notify:
            _safe(lambda: self.notify(
                f"\u23f8\ufe0f CareerPilot needs you: {kind.upper()} on "
                f"{portal or 'a portal'}.\n{reason}\nURL: {url}"), None)

        return InteractionBundle(kind, state, reason, url, shot, html, meta_path)

    def _screenshot(self, page: Any, path: str) -> str:
        try:
            page.screenshot(path=path)
            return path
        except Exception as exc:  # noqa: BLE001
            logger.warning("Screenshot capture failed: %s", exc)
            return ""

    def _html(self, page: Any, path: str) -> str:
        try:
            Path(path).write_text(page.content())
            return path
        except Exception as exc:  # noqa: BLE001
            logger.warning("HTML capture failed: %s", exc)
            return ""


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default
