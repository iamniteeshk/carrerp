"""Run metrics collector.

A lightweight tally the Browser Engine and pipeline increment during a scan, so
the Performance analyzer and session report have real numbers. Thread-safe-ish
(single scan thread); never raises.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunMetrics:
    pages_visited: int = 0
    jobs_opened: int = 0
    jobs_parsed: int = 0
    jobs_rejected: int = 0
    jobs_selected: int = 0
    jobs_queued: int = 0
    jobs_applied: int = 0
    selectors_failed: int = 0
    retries: int = 0
    timeouts: int = 0
    ai_failures: int = 0
    portal_failures: int = 0
    csv_updates: int = 0
    db_updates: int = 0
    evidence_bundles: int = 0
    searches: list = field(default_factory=list)
    locations: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    _read_ms: list = field(default_factory=list)
    _scroll_ms: list = field(default_factory=list)
    _job_ms: list = field(default_factory=list)
    _ai_ms: list = field(default_factory=list)
    _rule_ms: list = field(default_factory=list)

    def incr(self, field_name: str, by: int = 1) -> None:
        try:
            setattr(self, field_name, getattr(self, field_name) + by)
        except Exception:  # noqa: BLE001
            pass

    def timing(self, kind: str, ms: float) -> None:
        lst = getattr(self, f"_{kind}_ms", None)
        if lst is not None:
            lst.append(ms)

    def note(self, msg: str) -> None:
        self.warnings.append(msg)

    @staticmethod
    def _avg(xs: list) -> int:
        return int(sum(xs) / len(xs)) if xs else 0

    def as_dict(self) -> dict:
        return {
            "pages_visited": self.pages_visited, "jobs_opened": self.jobs_opened,
            "jobs_parsed": self.jobs_parsed, "jobs_rejected": self.jobs_rejected,
            "jobs_selected": self.jobs_selected, "jobs_queued": self.jobs_queued,
            "jobs_applied": self.jobs_applied,
            "selectors_failed": self.selectors_failed, "retries": self.retries,
            "timeouts": self.timeouts, "ai_failures": self.ai_failures,
            "portal_failures": self.portal_failures,
            "csv_updates": self.csv_updates, "db_updates": self.db_updates,
            "evidence_bundles": self.evidence_bundles,
            "avg_read_ms": self._avg(self._read_ms),
            "avg_scroll_ms": self._avg(self._scroll_ms),
            "avg_job_ms": self._avg(self._job_ms),
            "avg_ai_ms": self._avg(self._ai_ms),
            "avg_rule_ms": self._avg(self._rule_ms),
            "searches": self.searches, "locations": self.locations,
            "warnings": self.warnings,
        }
