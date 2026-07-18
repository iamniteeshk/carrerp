"""Scheduler (APScheduler).

Runs the scan pipeline at the configured interval, sends a daily summary, and
runs retention maintenance so a 24x7 deployment does not grow without bound.
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
                 reporter=None, backup_path: str = "", summary_hour: int = 20,
                 maintenance_hour: int = 3, app_config=None):
        self.pipeline = pipeline
        self.interval_hours = interval_hours
        self.telegram = telegram
        self.jobs = job_service
        self.reporter = reporter
        self.backup_path = backup_path
        self.summary_hour = summary_hour
        self.maintenance_hour = maintenance_hour
        self.app_config = app_config
        # ONE worker thread: Playwright sync objects are thread-bound, so every
        # scan (immediate and recurring) must run on the same thread.
        self._scheduler = BackgroundScheduler(
            daemon=True, executors={"default": ThreadPoolExecutor(max_workers=1)})
        self._consecutive_failures = 0

    # Probability a recurring cycle is skipped, so the schedule is not perfectly
    # regular (humans do not search on a fixed clock / every single day).
    SKIP_CYCLE_PROBABILITY = 0.15
    MAX_BACKOFF_SECONDS = 900  # 15 minutes cap after repeated scan crashes

    def start(self, run_immediately: bool = True) -> None:
        self._scheduler.add_job(
            self._safe_scan, "interval", hours=self.interval_hours,
            id="scan", max_instances=1, coalesce=True, args=[True])
        self._scheduler.add_job(
            self._daily_summary, "cron", hour=self.summary_hour, minute=0,
            id="summary")
        self._scheduler.add_job(
            self._daily_maintenance, "cron", hour=self.maintenance_hour, minute=15,
            id="maintenance")
        # Drain ops-dashboard control queue even when no scan is due.
        self._scheduler.add_job(
            self.drain_ops_commands, "interval", seconds=15,
            id="ops_commands", max_instances=1, coalesce=True)
        if run_immediately:
            # Run the first scan ON THE SCHEDULER'S WORKER THREAD (not the main
            # thread), so Playwright is created and reused on one thread. The
            # first scan always runs (allow_skip=False).
            self._scheduler.add_job(self._safe_scan, "date",
                                    run_date=datetime.now(), id="initial_scan")
        self._scheduler.start()
        logger.info("Scheduler started (every %sh, maintenance at %02d:15)",
                    self.interval_hours, self.maintenance_hour)

    def _safe_scan(self, allow_skip: bool = False) -> None:
        # Recurring (unattended) cycles honour the human time-of-day session and
        # portal schedule; the immediate first scan (allow_skip=False) runs
        # everything now so `run` is usable for testing/debugging.
        try:
            self.pipeline.honor_session_windows = bool(allow_skip)
        except Exception:  # noqa: BLE001
            pass
        if allow_skip:
            import random
            if random.random() < self.SKIP_CYCLE_PROBABILITY:
                logger.info("Skipping this scan cycle (human-like: not every "
                            "cycle is used)")
                return
        try:
            # Honour ops-dashboard pause + drain control queue on the worker thread.
            self.drain_ops_commands()
            try:
                from ..ops_dashboard.runtime import HUB
                if HUB.paused:
                    logger.info("Scan skipped — ops dashboard paused")
                    from ..core.maintenance import write_health_heartbeat
                    write_health_heartbeat(status="paused")
                    return
            except Exception:  # noqa: BLE001
                pass
            from ..core.maintenance import write_health_heartbeat
            write_health_heartbeat(status="scanning")
            self.pipeline.run_once()
            write_health_heartbeat(status="ok")
            self._consecutive_failures = 0
            self.drain_ops_commands()
        except Exception as exc:  # noqa: BLE001
            self._consecutive_failures = getattr(self, "_consecutive_failures", 0) + 1
            logger.exception("Scheduled scan crashed: %s", exc)
            try:
                from ..core.maintenance import write_health_heartbeat
                write_health_heartbeat(status="error", extra={"error": str(exc)})
            except Exception:  # noqa: BLE001
                pass
            try:
                from ..core.win_events import EventKind, write_event
                write_event(EventKind.SCHEDULER,
                            f"Scan cycle crashed (#{self._consecutive_failures}): {exc}")
                write_event(EventKind.RECOVERY,
                            f"Will retry next interval; consecutive failures="
                            f"{self._consecutive_failures}")
            except Exception:  # noqa: BLE001
                pass
            self.telegram.send(NotificationType.CRITICAL_ERROR,
                               f"Scan cycle crashed: {exc}")
            # Exponential backoff sleep so a tight crash loop does not hammer
            # the machine; APScheduler still owns the next interval.
            import time
            delay = min(2 ** self._consecutive_failures, self.MAX_BACKOFF_SECONDS)
            logger.warning("Backing off %ss after scan failure #%s",
                           delay, self._consecutive_failures)
            time.sleep(delay)

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
            # Full dated backup tree (config/db/profiles/logs/reports).
            try:
                from ..core.backup_ops import create_backup
                cfg = self.app_config
                create_backup(
                    database_path=getattr(cfg, "database_path",
                                          "database/careerpilot.db") if cfg else
                    "database/careerpilot.db",
                    profiles_dir=getattr(cfg, "profiles_dir", "profiles")
                    if cfg else "profiles",
                    browser_profiles=getattr(cfg, "browser_profiles_path",
                                             "profiles_browser") if cfg else
                    "profiles_browser",
                    logs_dir=getattr(cfg, "log_path", "logs") if cfg else "logs",
                    reports_dir=getattr(cfg, "report_path", "reports")
                    if cfg else "reports",
                    include_chrome_profiles=False,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Full daily backup failed: %s", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Daily summary/backup failed: %s", exc)

    def _daily_maintenance(self) -> None:
        """Retention cleanup so long-running installs do not grow forever."""
        try:
            from ..core.maintenance import RetentionConfig, run_maintenance
            cfg = self.app_config
            ret = getattr(cfg, "retention", None) if cfg is not None else None
            retention = RetentionConfig(
                cache_days=getattr(ret, "cache_days", 30),
                report_days=getattr(ret, "report_days", 60),
                screenshot_days=getattr(ret, "screenshot_days", 14),
                evidence_days=getattr(ret, "evidence_days", 14),
                backup_days=getattr(ret, "backup_days", 30),
                human_interaction_days=getattr(ret, "human_interaction_days", 14),
                session_history_max=getattr(ret, "session_history_max", 500),
                good_jobs_max=getattr(ret, "good_jobs_max", 1000),
                vacuum_db=getattr(ret, "vacuum_db", True),
            ) if ret is not None else RetentionConfig()
            result = run_maintenance(
                cache_dir="cache/jobs",
                report_dir=getattr(cfg, "report_path", "reports") if cfg else "reports",
                screenshot_dir=(getattr(cfg, "screenshot_path", "screenshots")
                                if cfg else "screenshots"),
                evidence_dir=(getattr(getattr(cfg, "debug", None), "evidence_dir",
                                      "debug") if cfg else "debug"),
                backup_dir=getattr(cfg, "backup_path", "database/backups")
                if cfg else "database/backups",
                database_path=getattr(cfg, "database_path", "") if cfg else "",
                config=retention,
            )
            logger.info("Daily maintenance: %s", result.as_dict())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Daily maintenance failed: %s", exc)

    def is_running(self) -> bool:
        try:
            return bool(self._scheduler.running)
        except Exception:  # noqa: BLE001
            return False

    def status(self) -> dict:
        """Read-only snapshot for the ops dashboard (no side effects)."""
        jobs = []
        next_scan = None
        try:
            for job in self._scheduler.get_jobs():
                nxt = job.next_run_time.isoformat() if job.next_run_time else None
                jobs.append({
                    "id": job.id,
                    "name": job.name or job.id,
                    "next_run_time": nxt,
                    "trigger": str(job.trigger),
                })
                if job.id in ("scan", "initial_scan") and nxt:
                    if next_scan is None or nxt < next_scan:
                        next_scan = nxt
        except Exception as exc:  # noqa: BLE001
            return {
                "running": self.is_running(),
                "error": str(exc),
                "interval_hours": self.interval_hours,
                "consecutive_failures": self._consecutive_failures,
                "jobs": [],
            }
        return {
            "running": self.is_running(),
            "interval_hours": self.interval_hours,
            "summary_hour": self.summary_hour,
            "maintenance_hour": self.maintenance_hour,
            "consecutive_failures": self._consecutive_failures,
            "next_scan": next_scan,
            "queue_length": len(jobs),
            "jobs": jobs,
        }

    def drain_ops_commands(self) -> None:
        """Execute control commands queued by the ops dashboard (safe thread)."""
        try:
            from ..ops_dashboard.runtime import HUB
            cmds = HUB.drain_commands()
        except Exception:  # noqa: BLE001
            return
        for cmd in cmds:
            action = (cmd.action or "").lower()
            try:
                if action == "restart_browser":
                    self._restart_browser()
                elif action == "backup":
                    self._ops_backup()
                elif action == "doctor":
                    self._ops_doctor()
                elif action == "scan_now":
                    self._safe_scan(allow_skip=False)
                else:
                    logger.warning("Unknown ops command: %s", action)
            except Exception:  # noqa: BLE001
                logger.exception("Ops command failed: %s", action)

    def _restart_browser(self) -> None:
        from ..ops_dashboard.activity import emit
        from ..ops_dashboard.runtime import HUB
        browser = HUB.browser
        if browser is None:
            emit("Restart browser requested but browser not bound",
                 level="warn", category="browser")
            return
        try:
            browser.close_all()
            HUB.note_browser_restart()
            emit("Browser restarted by operator", level="warn", category="browser")
        except Exception as exc:  # noqa: BLE001
            emit(f"Browser restart failed: {exc}", level="error", category="browser")

    def _ops_backup(self) -> None:
        from ..ops_dashboard.activity import emit
        from ..core.backup_ops import create_backup
        cfg = self.app_config
        create_backup(
            database_path=getattr(cfg, "database_path", "database/careerpilot.db")
            if cfg else "database/careerpilot.db",
            profiles_dir=getattr(cfg, "profiles_dir", "profiles") if cfg else "profiles",
            browser_profiles=getattr(cfg, "browser_profiles_path", "profiles_browser")
            if cfg else "profiles_browser",
            logs_dir=getattr(cfg, "log_path", "logs") if cfg else "logs",
            reports_dir=getattr(cfg, "report_path", "reports") if cfg else "reports",
            include_chrome_profiles=False,
        )
        emit("Operator backup completed", level="success", category="system")

    def _ops_doctor(self) -> None:
        from ..ops_dashboard.activity import emit
        from ..core.doctor import run_doctor
        cfg = self.app_config
        path = getattr(cfg, "source_path", "config/config.yaml") if cfg else "config/config.yaml"
        ok = run_doctor(path)
        emit("Doctor PASS" if ok else "Doctor reported failures",
             level="success" if ok else "error", category="system")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")
            try:
                from ..ops_dashboard.activity import emit
                emit("Scheduler stopped", level="warn", category="scheduler")
            except Exception:  # noqa: BLE001
                pass
