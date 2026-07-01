"""Diagnostics Toolkit facade -- one object the rest of the app holds.

Bundles the recorder, the failure-evidence writer and the live-status sink, and
exposes the page exporter. Construct once (in main), inject where needed. When
``enabled`` is false everything is cheap/no-op so production behaviour is
unchanged.
"""

from __future__ import annotations

from pathlib import Path

from ..core.logging_setup import get_logger
from .evidence import FailureEvidence
from .exporter import export_page
from .live_status import LiveStatus
from .recorder import InteractionRecorder
from .metrics import RunMetrics
from .session_report import SessionReporter
from .analyzers import default_analyzers, diff_snapshots

logger = get_logger("careerpilot.diagnostics")


class DiagnosticsToolkit:
    def __init__(self, enabled: bool = False, base_dir: str | Path = "debug"):
        self.enabled = enabled
        self.base_dir = Path(base_dir)
        self.recorder = InteractionRecorder(enabled=enabled)
        self.evidence = FailureEvidence(base_dir=base_dir)
        self.status = LiveStatus()
        self.metrics = RunMetrics()
        # Plugin registry (#9): analyzers can be added without core changes.
        self.reporter = SessionReporter(base_dir=base_dir,
                                        analyzers=default_analyzers())

    def register_analyzer(self, analyzer) -> None:
        self.reporter.register(analyzer)

    def attach(self, page) -> None:
        if self.enabled:
            self.recorder.attach(page)

    def capture_failure(self, kind: str, page=None, **kwargs) -> str:
        if not self.enabled:
            logger.warning("[diagnostics] %s (enable debug.visual_mode for an "
                           "evidence bundle)", kind)
            return ""
        self.metrics.incr("evidence_bundles")
        return self.evidence.capture(kind, page, recorder=self.recorder, **kwargs)

    def export(self, page, dest, **kwargs) -> str:
        return export_page(page, dest, recorder=self.recorder, **kwargs)

    # ---- analysis (#1-#8) ----------------------------------------------

    def diagnose_failure(self, signals: dict) -> dict:
        """Self-diagnosing browser (#1/#4): explain a failure from page signals."""
        from .analyzers import FailureAnalyzer
        return FailureAnalyzer().analyze({"signals": signals}).as_dict()

    def diff_dom(self, baseline: dict, current: dict) -> dict:
        """DOM Difference Engine (#3)."""
        return diff_snapshots(baseline, current).as_dict()

    def session_report(self, counts: dict | None = None,
                        ctx_extra: dict | None = None) -> str:
        """Automatic Session Summary (#7): runs every analyzer plugin."""
        if not self.enabled:
            return ""
        return self.reporter.generate(
            metrics=self.metrics.as_dict(),
            events=self.recorder.events, counts=counts, ctx_extra=ctx_extra)


def build_snapshot(page, selectors: dict | None = None) -> dict:
    """Build a small DOM snapshot for the DOM Diff engine (#3): tag counts,
    class-name counts, and match counts for the selectors we rely on."""
    js = """
    (sel) => {
      const tags = {}; const classes = {};
      document.querySelectorAll('*').forEach(el => {
        tags[el.tagName.toLowerCase()] = (tags[el.tagName.toLowerCase()]||0)+1;
        el.classList.forEach(c => { classes[c] = (classes[c]||0)+1; });
      });
      const counts = {};
      for (const k in sel) {
        try { counts[k] = document.querySelectorAll(sel[k]).length; }
        catch(e) { counts[k] = -1; }
      }
      return {tag_counts: tags, classes: classes, selector_counts: counts};
    }
    """
    try:
        return page.evaluate(js, selectors or {})
    except Exception as exc:  # noqa: BLE001
        logger.debug("snapshot failed: %s", exc)
        return {"tag_counts": {}, "classes": {}, "selector_counts": {}}


def survey_card_candidates(page, limit: int = 12) -> list:
    """Survey the DOM for job-card-like containers (for the Selector Analyzer #2):
    classes whose elements repeat (lists of cards usually share a class)."""
    js = """
    (limit) => {
      const counts = {}; const sample = {};
      document.querySelectorAll('div,li,article,section').forEach(el => {
        el.classList.forEach(c => {
          counts[c] = (counts[c]||0)+1;
          if (!sample[c]) sample[c] = (el.innerText||'').trim().slice(0,80);
        });
      });
      return Object.keys(counts)
        .filter(c => counts[c] >= 3 && counts[c] <= 80)
        .map(c => ({selector: '.'+c, count: counts[c], sample_text: sample[c]}))
        .sort((a,b) => b.count - a.count).slice(0, limit);
    }
    """
    try:
        return page.evaluate(js, limit)
    except Exception as exc:  # noqa: BLE001
        logger.debug("survey failed: %s", exc)
        return []
