"""Automatic Session Summary (point #7) + analyzer orchestration.

At the end of a run this gathers the metrics, recorder events and any snapshots,
runs every registered analyzer plugin, and writes a single markdown report --
the first document to read after a run. Also writes the machine-readable JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from time import strftime

from ..core.logging_setup import get_logger
from .analyzers import default_analyzers

logger = get_logger("careerpilot.diagnostics.session")


class SessionReporter:
    def __init__(self, base_dir="debug", analyzers=None):
        self.base = Path(base_dir)
        self.analyzers = analyzers if analyzers is not None else default_analyzers()

    def register(self, analyzer) -> None:
        """Plugin hook -- add a custom analyzer without touching the core."""
        self.analyzers.append(analyzer)

    def run_analyzers(self, ctx: dict) -> list:
        results = []
        for a in self.analyzers:
            try:
                results.append(a.analyze(ctx))
            except Exception as exc:  # noqa: BLE001 - one analyzer never breaks the report
                logger.warning("Analyzer %s failed: %s",
                               getattr(a, "name", a), exc)
        return results

    def generate(self, *, metrics: dict, events: list | None = None,
                 counts: dict | None = None, ctx_extra: dict | None = None) -> str:
        ctx = {"metrics": metrics, "events": events or []}
        ctx.update(ctx_extra or {})
        results = self.run_analyzers(ctx)

        self.base.mkdir(parents=True, exist_ok=True)
        stamp = strftime("%Y%m%d-%H%M%S")
        md_path = self.base / f"session_report_{stamp}.md"
        json_path = self.base / f"session_report_{stamp}.json"

        c = counts or {}
        m = metrics or {}
        md = [f"# CareerPilot Session Report — {strftime('%Y-%m-%d %H:%M:%S')}", ""]
        md += ["## Summary", "",
               f"- Searches performed: {len(m.get('searches', []))}",
               f"- Locations searched: {', '.join(m.get('locations', [])) or '-'}",
               f"- Jobs discovered: {c.get('found', m.get('jobs_parsed', 0))}",
               f"- Jobs opened: {m.get('jobs_opened', 0)}",
               f"- Jobs rejected: {c.get('rejected', m.get('jobs_rejected', 0))}",
               f"- Jobs selected/matched: {c.get('matched', m.get('jobs_selected', 0))}",
               f"- Jobs queued: {m.get('jobs_queued', 0)}",
               f"- Jobs applied: {c.get('applied', m.get('jobs_applied', 0))}",
               f"- AI failures: {m.get('ai_failures', 0)}",
               f"- Portal failures: {m.get('portal_failures', 0)}",
               f"- Evidence bundles: {m.get('evidence_bundles', 0)}",
               f"- Selectors failed: {m.get('selectors_failed', 0)} | "
               f"retries: {m.get('retries', 0)} | timeouts: {m.get('timeouts', 0)}",
               ""]
        if m.get("warnings"):
            md += ["## Warnings", ""] + [f"- {w}" for w in m["warnings"]] + [""]
        md += ["## Analyzer findings", ""]
        for r in results:
            md.append(r.as_markdown())
            md.append("")

        md_text = "\n".join(md)
        try:
            md_path.write_text(md_text)
            json_path.write_text(json.dumps(
                {"counts": c, "metrics": m,
                 "analyzers": [r.as_dict() for r in results]}, indent=2,
                default=str))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Session report write failed: %s", exc)
        logger.info("Session report written -> %s", md_path)
        return str(md_path)
