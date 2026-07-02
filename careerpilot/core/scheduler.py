"""Scheduler (APScheduler).

Runs the scan pipeline at the configured interval and sends a daily summary.
Intervals are configurable (P003 §14). The scheduler catches pipeline errors
so a single bad cycle never kills the schedule.
"""

from __future__ import annotations

from datetime import datetime

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from ..core.enums import NotificationType
from ..core.logging_setup import get_logger
from ..core.pipeline import ScanPipeline
from ..db.services import JobService
from ..notify.telegram_service import TelegramService

logger = get_logger(__name__)


class Scheduler:
    def __init__(self, pipeline: ScanPipeline, interval_hours: int,
                 telegram: TelegramService, job_service: JobService,
                 reporter=None, backup_path: str = "", summary_hour: int = 20):
        self.pipeline = pipeline
        self.interval_hours = interval_hours
        self.telegram = telegram
        self.jobs = job_service
        self.reporter = reporter
        self.backup_path = backup_path
        self.summary_hour = summary_hour
        # ONE worker thread: Playwright sync objects are thread-bound, so every
        # scan (immediate and recurring) must run on the same thread.
        self._scheduler = BackgroundScheduler(
            daemon=True, executors={"default": ThreadPoolExecutor(max_workers=1)})

    # Probability a recurring cycle is skipped, so the schedule is not perfectly
    # regular (humans do not search on a fixed clock / every single day).
    SKIP_CYCLE_PROBABILITY = 0.15

    def start(self, run_immediately: bool = True) -> None:
        self._scheduler.add_job(
            self._safe_scan, "interval", hours=self.interval_hours,
            id="scan", max_instances=1, coalesce=True, args=[True])
        self._scheduler.add_job(
            self._daily_summary, "cron", hour=self.summary_hour, minute=0,
            id="summary")
        if run_immediately:
            # Run the first scan ON THE SCHEDULER'S WORKER THREAD (not the main
            # thread), so Playwright is created and reused on one thread. The
            # first scan always runs (allow_skip=False).
            self._scheduler.add_job(self._safe_scan, "date",
                                    run_date=datetime.now(), id="initial_scan")
        self._scheduler.start()
        logger.info("Scheduler started (every %sh)", self.interval_hours)

    def _safe_scan(self, allow_skip: bool = False) -> None:
        if allow_skip:
            import random
            if random.random() < self.SKIP_CYCLE_PROBABILITY:
                logger.info("Skipping this scan cycle (human-like: not every "
                            "cycle is used)")
                return
        try:
            self.pipeline.run_once()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduled scan crashed: %s", exc)
            self.telegram.send(NotificationType.CRITICAL_ERROR,
                               f"Scan cycle crashed: {exc}")

    def _daily_summary(self) -> None:
        try:
            if self.reporter is not None:
                text, _ = self.reporter.generate_daily_summary()
            else:
                counts = self.jobs.count_by_status()
                text = "Daily Summary\n" + "\n".join(
                    f"{k}: {v}" for k, v in counts.items())
            self.telegram.send(NotificationType.DAILY_SUMMARY, text)
            # Daily database backup alongside the summary.
            if self.backup_path:
                self.pipeline.scans.db.backup(self.backup_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Daily summary/backup failed: %s", exc)

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")
