"""Replay a recorded browser session.

Reads a recorder's ``replay.json`` and re-issues the interactions (navigate,
scroll, mouse move, click, key) against a page, preserving the recorded wait
gaps so the playback paces like the original. Useful for reproducing a bug
without the live site doing anything unexpected. Replay is best-effort: events
it can't re-issue are logged and skipped, never raised.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.diagnostics.replay")


def load_events(path: str | Path) -> list[dict]:
    p = Path(path)
    if p.is_dir():
        p = p / "replay.json"
    try:
        return json.loads(p.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load replay events from %s: %s", p, exc)
        return []


def replay(events, page, *, speed: float = 1.0, max_gap_ms: int = 4000) -> int:
    """Re-issue recorded events on ``page``. Returns the number replayed.

    ``speed`` scales the recorded inter-event gaps (2.0 = twice as fast);
    ``max_gap_ms`` caps any single wait so replay never hangs.
    """
    if isinstance(events, (str, Path)):
        events = load_events(events)
    replayed = 0
    last_t = None
    for ev in events:
        t = ev.get("t", 0)
        if last_t is not None and speed > 0:
            gap = min(max_gap_ms, int((t - last_t) * 1000 / speed))
            if gap > 0:
                _safe(lambda g=gap: page.wait_for_timeout(g))
        last_t = t
        kind = ev.get("kind")
        try:
            if kind == "navigate" and ev.get("url"):
                page.goto(ev["url"])
            elif kind == "scroll":
                page.evaluate(f"window.scrollTo(0, {int(ev.get('y', 0))})")
            elif kind == "mouse_move":
                page.mouse.move(ev.get("x", 0), ev.get("y", 0))
            elif kind == "click":
                page.mouse.click(ev.get("x", 0), ev.get("y", 0))
            elif kind == "key" and ev.get("value"):
                page.keyboard.press(ev["value"])
            else:
                continue  # transitions/hovers/waits are informational
            replayed += 1
            logger.info("[replay] %s %s", kind,
                        {k: v for k, v in ev.items() if k not in ("t", "kind")})
        except Exception as exc:  # noqa: BLE001 - replay must never crash
            logger.debug("[replay] skipped %s: %s", kind, exc)
    logger.info("[replay] replayed %s/%s events", replayed, len(events))
    return replayed


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None
