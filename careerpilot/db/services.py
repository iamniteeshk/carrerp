"""Database services.

All SQL lives here (per the coding standard: never scatter SQL across the app).
Other modules call these methods; they never touch the connection directly.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..core.enums import JobStatus
from ..core.logging_setup import get_logger
from ..core.models import ApplicationResult, Job
from .database import Database

logger = get_logger(__name__)

# Statuses that must be retried on a later scan (AI outage, partial JD, mid-apply crash).
RETRIABLE_STATUSES = {
    JobStatus.QUEUED.value,
    JobStatus.PARTIAL_DATA.value,
    JobStatus.APPLYING.value,
    JobStatus.FOUND.value,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobService:
    def __init__(self, db: Database):
        self.db = db

    def exists(self, job: Job) -> bool:
        """True if this job already has a terminal (non-retriable) DB row.

        Retriable statuses (QUEUED, PARTIAL_DATA, APPLYING, FOUND) do NOT count
        as exists — the pipeline must be able to resume them after AI outages
        or partial extraction failures.
        """
        row = self.find_existing(job)
        if row is None:
            return False
        status = (row.get("status") or "").upper()
        return status not in RETRIABLE_STATUSES

    def find_existing(self, job: Job) -> dict[str, Any] | None:
        conn = self.db.connect()
        if job.job_url:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_url = ?", (job.job_url,)
            ).fetchone()
            if row:
                return dict(row)
        row = conn.execute(
            "SELECT * FROM jobs WHERE lower(company)=? AND lower(job_title)=? "
            "AND lower(location)=?",
            (job.company.lower(), job.job_title.lower(), job.location.lower()),
        ).fetchone()
        return dict(row) if row else None

    def is_retriable(self, job: Job) -> bool:
        row = self.find_existing(job)
        if row is None:
            return False
        return (row.get("status") or "").upper() in RETRIABLE_STATUSES

    def insert(self, job: Job) -> int:
        conn = self.db.connect()
        cur = conn.execute(
            """INSERT OR IGNORE INTO jobs
               (portal, company, job_title, location, salary, experience,
                employment_type, shift, job_url, job_description, is_easy_apply,
                status, source_id, reading_ms, discovered_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job.portal, job.company, job.job_title, job.location, job.salary,
             job.experience, job.employment_type, job.shift, job.job_url,
             job.job_description, int(job.is_easy_apply), job.status.value,
             job.source_id, int(getattr(job, "reading_ms", 0) or 0),
             _now(), _now()),
        )
        conn.commit()
        return cur.lastrowid

    def update_status(self, job_id: int, status: JobStatus,
                      *, match_score: float | None = None,
                      selected_resume: str | None = None,
                      rejection_reason: str | None = None) -> None:
        conn = self.db.connect()
        conn.execute(
            """UPDATE jobs SET status=?, match_score=COALESCE(?, match_score),
               selected_resume=COALESCE(?, selected_resume),
               rejection_reason=COALESCE(?, rejection_reason), updated_at=?
               WHERE job_id=?""",
            (status.value, match_score, selected_resume, rejection_reason,
             _now(), job_id),
        )
        conn.commit()

    def get(self, job_id: int) -> dict[str, Any] | None:
        conn = self.db.connect()
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def count_by_status(self) -> dict[str, int]:
        conn = self.db.connect()
        rows = conn.execute(
            "SELECT status, COUNT(*) AS c FROM jobs GROUP BY status"
        ).fetchall()
        return {r["status"]: r["c"] for r in rows}


class ApplicationService:
    def __init__(self, db: Database):
        self.db = db

    def already_applied(self, job_id: int) -> bool:
        """True only when a successful live APPLIED row exists for this job.

        QUEUED / failed / dry-run rows must not permanently block a later apply.
        """
        conn = self.db.connect()
        row = conn.execute(
            "SELECT 1 FROM applications WHERE job_id=? AND dry_run=0 "
            "AND application_status='APPLIED'",
            (job_id,),
        ).fetchone()
        return row is not None

    def applied_today_count(self) -> int:
        conn = self.db.connect()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM applications "
            "WHERE dry_run=0 AND application_status='APPLIED' "
            "AND date(applied_at)=date('now')"
        ).fetchone()
        return row["c"] if row else 0

    def record(self, result: ApplicationResult) -> int:
        conn = self.db.connect()
        answers = json.dumps([a.__dict__ for a in result.screening_answers])
        cur = conn.execute(
            """INSERT INTO applications
               (job_id, company, portal, resume_used, resume_version, match_score,
                cover_letter, screening_answers, application_status,
                portal_reference, screenshot, dry_run, applied_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (result.job_id, result.company, result.portal, result.resume_used,
             result.resume_version, result.match_score, result.cover_letter,
             answers, result.status.value, result.portal_reference,
             result.screenshot_path, int(result.dry_run), _now()),
        )
        conn.commit()
        return cur.lastrowid


class AIHistoryService:
    def __init__(self, db: Database):
        self.db = db

    def record(self, *, provider: str, model: str, job_id: int | None,
               purpose: str, tokens_used: int, execution_time: float,
               success: bool) -> None:
        conn = self.db.connect()
        conn.execute(
            """INSERT INTO ai_history
               (provider, model, job_id, purpose, tokens_used, execution_time,
                success, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (provider, model, job_id, purpose, tokens_used, execution_time,
             int(success), _now()),
        )
        conn.commit()


class NotificationService:
    def __init__(self, db: Database):
        self.db = db

    def record(self, notification_type: str, message: str, sent: bool) -> int:
        conn = self.db.connect()
        cur = conn.execute(
            "INSERT INTO notifications (notification_type, message, sent, sent_at) "
            "VALUES (?,?,?,?)",
            (notification_type, message, int(sent), _now() if sent else None),
        )
        conn.commit()
        return cur.lastrowid


class FailedJobService:
    def __init__(self, db: Database):
        self.db = db

    def record(self, job_id: int | None, reason: str, retry_count: int,
               screenshot: str = "") -> None:
        conn = self.db.connect()
        conn.execute(
            "INSERT INTO failed_jobs (job_id, reason, retry_count, screenshot, "
            "last_attempt) VALUES (?,?,?,?,?)",
            (job_id, reason, retry_count, screenshot, _now()),
        )
        conn.commit()


class ScanService:
    def __init__(self, db: Database):
        self.db = db

    def start(self) -> int:
        conn = self.db.connect()
        cur = conn.execute(
            "INSERT INTO scan_history (started_at, status) VALUES (?, 'RUNNING')",
            (_now(),),
        )
        conn.commit()
        return cur.lastrowid

    def finish(self, scan_id: int, *, found: int, rejected: int, matched: int,
               applied: int, portals: int, duration: float,
               status: str = "COMPLETED") -> None:
        conn = self.db.connect()
        conn.execute(
            """UPDATE scan_history SET finished_at=?, portals_scanned=?,
               jobs_found=?, jobs_rejected=?, jobs_matched=?, jobs_applied=?,
               duration_seconds=?, status=? WHERE scan_id=?""",
            (_now(), portals, found, rejected, matched, applied, duration,
             status, scan_id),
        )
        conn.commit()
