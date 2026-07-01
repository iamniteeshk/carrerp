"""Interaction / console / network recorder.

Records every browser interaction (mouse move, click, hover, scroll, key,
navigation, wait) plus console messages and network requests into an ordered,
timestamped event log that can be saved to JSON and replayed. Attaching to a
page wires the console/network listeners. AI-free; never raises into the caller.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.diagnostics.recorder")


class InteractionRecorder:
    def __init__(self, enabled: bool = True, max_events: int = 5000):
        self.enabled = enabled
        self.max_events = max_events
        self.events: list[dict] = []
        self.console: list[dict] = []
        self.network: list[dict] = []
        self._t0 = time.time()
        self._attached: set[int] = set()

    # ---- generic event log ---------------------------------------------

    def record(self, kind: str, **data) -> None:
        if not self.enabled:
            return
        self.events.append({"t": round(time.time() - self._t0, 3),
                            "kind": kind, **data})
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

    # convenience wrappers (used across the Browser Engine)
    def mouse_move(self, x, y): self.record("mouse_move", x=round(x), y=round(y))
    def click(self, x, y): self.record("click", x=round(x), y=round(y))
    def hover(self, target): self.record("hover", target=str(target))
    def scroll(self, y, pct=None): self.record("scroll", y=int(y), pct=pct)
    def key(self, value): self.record("key", value=str(value))
    def navigate(self, url): self.record("navigate", url=url)
    def transition(self, state): self.record("transition", state=str(state))
    def wait(self, reason, ms=None): self.record("wait", reason=reason, ms=ms)

    # ---- console + network (attach once per page) ----------------------

    def attach(self, page) -> None:
        if not self.enabled or id(page) in self._attached:
            return
        try:
            page.on("console", self._on_console)
            page.on("requestfinished", self._on_request)
            page.on("requestfailed", self._on_request_failed)
            self._attached.add(id(page))
        except Exception as exc:  # noqa: BLE001 - listeners must never crash a run
            logger.debug("recorder attach failed: %s", exc)

    def _on_console(self, msg) -> None:
        try:
            self.console.append({"t": round(time.time() - self._t0, 3),
                                "type": msg.type, "text": msg.text[:500]})
        except Exception:  # noqa: BLE001
            pass

    def _on_request(self, request) -> None:
        try:
            resp = request.response()
            self.network.append({
                "t": round(time.time() - self._t0, 3),
                "method": request.method, "url": request.url[:300],
                "status": resp.status if resp else None,
                "type": request.resource_type})
        except Exception:  # noqa: BLE001
            pass

    def _on_request_failed(self, request) -> None:
        try:
            self.network.append({
                "t": round(time.time() - self._t0, 3),
                "method": request.method, "url": request.url[:300],
                "status": "FAILED", "failure": str(request.failure)[:200],
                "type": request.resource_type})
        except Exception:  # noqa: BLE001
            pass

    # ---- persistence ----------------------------------------------------

    def save(self, folder: str | Path) -> dict:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        out = {}
        for name, data in (("replay.json", self.events),
                           ("console.log", self.console),
                           ("network.json", self.network)):
            path = folder / name
            try:
                if name == "console.log":
                    path.write_text("\n".join(
                        f"[{c['t']}] {c['type']}: {c['text']}" for c in data))
                else:
                    path.write_text(json.dumps(data, indent=2))
                out[name] = str(path)
            except Exception as exc:  # noqa: BLE001
                logger.debug("recorder save failed (%s): %s", name, exc)
        return out
