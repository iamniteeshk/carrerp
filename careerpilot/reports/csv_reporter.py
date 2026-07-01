"""End-of-scan CSV summaries generated from the SQLite database."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from ..core.logging_setup import get_logger
from ..db.database import Database

logger = get_logger(__name__)


class CSVReporter:
    def __init__(self, db: Database, report_dir: str | Path):
        self.db = db
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def _write(self, filename: str, fieldnames: list[str], rows: list[dict]) -> Path:
        path = self.report_dir / filename
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return path

    def generate_all(self) -> list[str]:
        """Write summary CSVs from current DB state. Returns paths written."""
        conn = self.db.connect()
        paths: list[str] = []

        def q(sql: str, params: tuple = ()) -> list[dict]:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

        summaries = [
            ("jobs_found.csv", "SELECT * FROM jobs WHERE status='FOUND' ORDER BY discovered_at DESC"),
            ("jobs_rejected.csv", "SELECT * FROM jobs WHERE status='REJECTED' ORDER BY updated_at DESC"),
            ("jobs_matched.csv", "SELECT * FROM jobs WHERE status='MATCHED' ORDER BY updated_at DESC"),
            ("jobs_applied.csv",
             "SELECT j.*, a.application_status, a.applied_at FROM applications a "
             "JOIN jobs j ON j.job_id=a.job_id WHERE a.dry_run=0 ORDER BY a.applied_at DESC"),
            ("failed_jobs.csv",
             "SELECT fj.*, j.portal, j.company, j.job_title, j.job_url "
             "FROM failed_jobs fj LEFT JOIN jobs j ON j.job_id=fj.job_id "
             "ORDER BY fj.last_attempt DESC"),
        ]
        cols = ["job_id", "portal", "company", "job_title", "location", "salary",
                "experience", "job_url", "status", "match_score", "rejection_reason",
                "discovered_at", "updated_at"]
        for filename, sql in summaries:
            rows = q(sql)
            if rows:
                fields = list(rows[0].keys())
            else:
                fields = cols
            p = self._write(filename, fields, rows)
            paths.append(str(p))

        logger.info("Generated %s summary CSV(s) in %s", len(paths), self.report_dir)
        return paths

    def generate_daily_summary(self) -> tuple[str, Path]:
        conn = self.db.connect()
        by_status = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) c FROM jobs GROUP BY status").fetchall()}
        applied = conn.execute(
            "SELECT COUNT(*) c FROM applications WHERE dry_run=0").fetchone()["c"]
        failed = conn.execute("SELECT COUNT(*) c FROM failed_jobs").fetchone()["c"]
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            f"CareerPilot Daily Summary — {ts}",
            f"Jobs by status: {by_status}",
            f"Applications (live): {applied}",
            f"Failed jobs (recorded): {failed}",
        ]
        text = "\n".join(lines)
        path = self.report_dir / f"daily_summary_{datetime.now(timezone.utc):%Y%m%d}.txt"
        path.write_text(text, encoding="utf-8")
        return text, path
