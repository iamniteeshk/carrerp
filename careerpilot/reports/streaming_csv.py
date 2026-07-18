"""Live per-state CSV writer -- appends a row the instant a job changes state."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from ..core.logging_setup import get_logger

logger = get_logger(__name__)

_COMMON = [
    "timestamp", "job_id", "portal", "company", "job_title", "location",
    "salary", "experience", "job_url", "status", "detail",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(job, status: str, detail: str = "", **extra) -> dict:
    return {
        "timestamp": _now(),
        "job_id": getattr(job, "job_id", "") or "",
        "portal": getattr(job, "portal", "") or "",
        "company": getattr(job, "company", "") or "",
        "job_title": getattr(job, "job_title", "") or "",
        "location": getattr(job, "location", "") or "",
        "salary": getattr(job, "salary", "") or "",
        "experience": getattr(job, "experience", "") or "",
        "job_url": getattr(job, "job_url", "") or "",
        "status": status,
        "detail": detail,
        **extra,
    }


def _portal_slug(job) -> str:
    return (getattr(job, "portal", "") or "unknown").strip().lower() or "unknown"


class StreamingCSVReporter:
    """Append-only CSV files written as each job reaches a terminal state.

    When ``per_portal`` is True, each job's rows are written under a portal
    subdirectory (e.g. ``reports/naukri/FoundJobs.csv``,
    ``reports/linkedin/FoundJobs.csv``) so Naukri and LinkedIn never mix. When
    False (default), files are written flat in ``report_dir`` (legacy behaviour).
    """

    def __init__(self, report_dir: str | Path, per_portal: bool = False):
        self.report_dir = Path(report_dir)
        self.per_portal = per_portal
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def _dir_for(self, job) -> Path:
        if not self.per_portal:
            return self.report_dir
        d = self.report_dir / _portal_slug(job)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _append(self, job, filename: str, fieldnames: list[str], row: dict) -> None:
        path = self._dir_for(job) / filename
        write_header = not path.exists() or path.stat().st_size == 0
        try:
            with path.open("a", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
                if write_header:
                    w.writeheader()
                w.writerow(row)
        except OSError as exc:
            logger.warning("Could not append to %s: %s", path, exc)

    def found(self, job) -> None:
        self._append(job, "FoundJobs.csv", _COMMON,
                     _row(job, "FOUND", "discovered"))

    def rejected(self, job, reason: str) -> None:
        self._append(job, "RejectedJobs.csv", _COMMON,
                     _row(job, "REJECTED", reason))

    def selected(self, job) -> None:
        self._append(job, "SelectedJobs.csv", _COMMON,
                     _row(job, "SELECTED", "passed Rule Engine"))

    def matched(self, job, score: float, profile: str) -> None:
        fields = _COMMON + ["match_score", "career_profile"]
        self._append(job, "MatchedJobs.csv", fields,
                     _row(job, "MATCHED", f"score={score}",
                          match_score=score, career_profile=profile))

    def applied(self, job, dry_run: bool) -> None:
        label = "DRY_RUN_READY" if dry_run else "APPLIED"
        self._append(job, "AppliedJobs.csv", _COMMON,
                     _row(job, label, "application recorded"))

    def failed(self, job, reason: str) -> None:
        self._append(job, "FailedJobs.csv", _COMMON,
                     _row(job, "FAILED", reason))
