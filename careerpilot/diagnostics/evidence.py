"""Automatic failure-evidence bundles.

Whenever something unexpected happens -- selector failure, timeout, CAPTCHA, OTP,
unexpected redirect, browser crash, network error, AI error -- this writes a
self-contained bundle (screenshot, HTML, browser/workflow state, URL, job,
search, location, timeline, console, network) so the problem can be diagnosed
without reproducing it. Never raises into the caller.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import strftime

from ..core.logging_setup import get_logger
from .exporter import export_page

logger = get_logger("careerpilot.diagnostics.evidence")


class FailureEvidence:
    def __init__(self, base_dir: str | Path = "debug"):
        self.base = Path(base_dir) / "failures"
        self._seq = 0

    def capture(self, kind: str, page=None, *, context: dict | None = None,
                selectors: dict | None = None, parsed: list | None = None,
                recorder=None, timeline: list | None = None) -> str:
        """Save a failure bundle for ``kind`` and return the folder path."""
        self._seq += 1
        stamp = strftime("%Y%m%d-%H%M%S")
        folder = self.base / f"{kind}_{stamp}_{self._seq:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        ctx = dict(context or {})
        ctx["failure_kind"] = kind

        logger.warning("[evidence] %s -- capturing failure bundle at %s | %s",
                       kind, folder, {k: ctx.get(k) for k in
                                      ("portal", "search", "url", "job")})
        if page is not None:
            export_page(page, folder, meta=ctx, selectors=selectors,
                        parsed=parsed, recorder=recorder, timeline=timeline)
        else:
            # No page (e.g. AI error) -- still record the context.
            try:
                (folder / "failure.json").write_text(json.dumps(ctx, indent=2))
            except Exception as exc:  # noqa: BLE001
                logger.debug("evidence write failed: %s", exc)
        return str(folder)
