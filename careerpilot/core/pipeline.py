"""Scan pipeline -- one full discovery->apply cycle (P004).

Order is fixed and matches the spec: collect -> store FOUND -> dedupe ->
Rule Engine -> AI -> resume/score -> Auto Apply -> persist -> report. AI runs
only on jobs that survive the Rule Engine. Any single job failing never stops
the cycle.
"""

from __future__ import annotations

import time

from ..ai.engine import AIEngine, AIUnavailable
from ..apply.auto_apply import AutoApplyEngine
from ..collectors.manager import CollectorManager
from ..core.config import AppConfig
from ..core.enums import ApplyMode, JobStatus
from ..core.logging_setup import get_logger
from ..core.models import AIEvaluation, Job
from ..core.state import StateMachine, WorkflowState
from ..db.services import FailedJobService
from ..db.services import JobService, ScanService, material_field_changes
from ..reports.csv_reporter import CSVReporter
from ..reports.streaming_csv import StreamingCSVReporter
from ..rules.rule_engine import RuleEngine

logger = get_logger(__name__)


def _terminal_failure_reason(job: Job) -> str:
    """Build a precise, actionable failure reason -- never generic."""
    detail = getattr(job, "failure_detail", "") or ""
    if detail:
        return detail
    rs = getattr(job, "read_status", "UNREAD")
    missing = getattr(job, "missing_fields", None) or []
    if rs == "UNREAD":
        if missing:
            return str(missing[0])
        return ("EXTRACTION_FAILED: job never opened "
                "(enable browser.open_jobs and ensure detail reader is wired)")
    if rs == "PARTIAL":
        if missing:
            return (f"EXTRACTION_FAILED: incomplete JD after open "
                    f"(missing {', '.join(str(m) for m in missing)})")
        return "EXTRACTION_FAILED: job opened but JD extraction incomplete"
    return f"PIPELINE_FAILED: unexpected read_status={rs}"


class ScanPipeline:
    def __init__(self, config: AppConfig, collector: CollectorManager,
                 rules: RuleEngine, ai: AIEngine, apply_engine: AutoApplyEngine,
                 job_service: JobService, scan_service: ScanService,
                 reporter: CSVReporter, notifier=None):
        self.cfg = config
        self.collector = collector
        self.rules = rules
        self.ai = ai
        self.apply_engine = apply_engine
        self.jobs = job_service
        self.scans = scan_service
        self.reporter = reporter
        # Live per-state CSVs (FoundJobs/RejectedJobs/SelectedJobs/Matched/Applied)
        # written as each job changes state, so progress is visible mid-scan and
        # nothing is lost on a crash.
        # Per-portal live CSVs: reports/naukri/*.csv, reports/linkedin/*.csv so
        # the two portals never mix (much easier debugging).
        self.stream = StreamingCSVReporter(reporter.report_dir, per_portal=True)
        self._job_seq = 0
        self._found = 0            # inserted (FOUND) jobs this run -> session cap
        self.status_sink = None  # diagnostics.LiveStatus (optional)
        self.diagnostics = None   # DiagnosticsToolkit (optional)
        self.notifier = notifier
        self._ai_notified = False
        # Route stranded jobs (Partial Data / no decision) to failed_jobs.csv so
        # every discovered job ends in exactly one terminal outcome.
        self.failed_jobs = FailedJobService(job_service.db)
        self._run_log: list = []   # accumulated per-job stage trace -> run_log.md
        # A job the AI scores below this becomes REJECTED instead of MATCHED, so
        # the Rule Engine and the AI agree on the final decision. 0 disables it.
        self.min_match_score = float(
            getattr(getattr(config, "rules", None), "minimum_match_score", 0) or 0)
        # Human-like session limits (set by main from a SessionPlan). 0/None off.
        self.session_max_jobs = 0
        self.session_deadline = None      # epoch seconds, or None
        # When True (autonomous 'run'), the session plan is time-of-day aware and
        # selects which portal(s) to use (morning=LinkedIn, lunch=Naukri, evening
        # =both). Manual 'scan' leaves this False so it always scans everything.
        self.honor_session_windows = False
        self._all_portals = None          # snapshot of the full portal list
        # Optional learning stores (set by main). Persistence must never crash.
        self.good_jobs = None             # learning.GoodJobsStore
        self.session_history = None       # learning.SessionHistoryStore
        self.session_plan = None          # learning.SessionPlan (for history)

    def _apply_session_plan(self, now=None) -> None:
        """Shape this run.

        MANUAL mode (``honor_session_windows`` False -- the `scan` command and the
        immediate first scan of `run`): ignore time windows entirely -- no time
        budget, no job cap, ALL enabled portals -- so Chrome opens and jobs are
        processed immediately (useful for testing/debugging).

        AUTOMATED mode (``honor_session_windows`` True -- recurring unattended
        scans): apply the human time-of-day session (morning=short LinkedIn,
        lunch=Naukri, evening=both with an idle gap, weekend longer, off-hours
        skipped) with a randomized duration budget, job cap and portal order.

        Never raises.
        """
        try:
            import random
            from datetime import datetime
            from .learning import SessionPlan, plan_daily_session
            kws = list(getattr(self.collector, "keywords", []) or [])
            rng = random.Random()

            if not self.honor_session_windows:
                # ---- MANUAL: no windows, no caps, all portals, start now ----
                if kws:
                    rng.shuffle(kws)
                    self.collector.keywords = kws
                # Restore the full portal list in case a prior automated scan
                # narrowed it (defensive; manual must always use every portal).
                if self._all_portals is not None:
                    self.collector.portals = list(self._all_portals)
                self.session_max_jobs = 0        # 0 = unlimited
                self.session_deadline = None      # no time budget
                self.session_plan = SessionPlan(
                    skip_today=False, window="manual", duration_minutes=0,
                    max_jobs=0, is_weekend=False, keywords=kws,
                    portals=[getattr(p, "portal_name", "")
                             for p in getattr(self.collector, "portals", [])],
                    idle_gaps=[])
                logger.info("Session plan: MANUAL run (no time window, no caps, "
                            "all portals) | portals=%s", self.session_plan.portals)
                return

            # ---- AUTOMATED: operator schedule (batches/fixed) or human_random ----
            from .schedule_config import plan_from_schedule, schedule_from_dict
            cfg = getattr(self, "cfg", None)
            schedule = getattr(cfg, "schedule", None) if cfg is not None else None
            settings = getattr(self, "settings", None)
            if settings is not None:
                override = settings.get_json("schedule_json")
                if isinstance(override, dict) and override:
                    schedule = schedule_from_dict(override)
            # Tests / minimal harnesses without AppConfig keep legacy random windows.
            if schedule is None and cfg is None:
                plan = plan_daily_session(rng, now or datetime.now(), kws)
            else:
                if schedule is None:
                    schedule = schedule_from_dict({})
                used = 0
                hist = getattr(self, "session_history", None)
                if hist is not None and hasattr(hist, "all"):
                    try:
                        from .schedule_config import minutes_used_today
                        used = minutes_used_today(hist.all(), now or datetime.now())
                    except Exception:  # noqa: BLE001
                        used = 0
                if schedule.mode == "human_random":
                    plan = plan_daily_session(
                        rng, now or datetime.now(), kws,
                        skip_probability=float(schedule.skip_probability or 0.12))
                else:
                    plan = plan_from_schedule(
                        schedule, now or datetime.now(), rng, keywords=kws,
                        used_minutes_today=used)
            self.session_plan = plan
            self.session_max_jobs = plan.max_jobs
            self.session_deadline = (time.time() + plan.duration_minutes * 60
                                     if plan.duration_minutes else None)
            if plan.keywords:
                self.collector.keywords = plan.keywords   # randomized this run
            # Portal selection (time-of-day). Snapshot the full list once so we
            # always select from all portals, never from a previous subset.
            if self._all_portals is None:
                self._all_portals = list(getattr(self.collector, "portals", []))
            if plan.portals:
                selected = [p for p in self._all_portals
                            if getattr(p, "portal_name", "") in plan.portals]
                # Fall back to all only if none of the named portals exist.
                self.collector.portals = selected or list(self._all_portals)
            else:
                # Off-hours / skip-day: a human is not searching -> no portal.
                self.collector.portals = []
            logger.info("Session plan: mode=%s window=%s duration=%smin max_jobs=%s "
                        "portals=%s keyword_order=%s",
                        getattr(schedule, "mode", "legacy"), plan.window,
                        plan.duration_minutes, plan.max_jobs, plan.portals,
                        plan.keywords[:5])
        except Exception as exc:  # noqa: BLE001 - planning must never crash a scan
            logger.warning("Session planning failed (using defaults): %s", exc)

    def _session_limit_reached(self) -> bool:
        """True once this run has hit its human-like job cap or time budget."""
        cap = getattr(self, "session_max_jobs", 0) or 0
        if cap and self._found >= cap:
            return True
        deadline = getattr(self, "session_deadline", None)
        if deadline and time.time() >= deadline:
            return True
        return False

    def _process_manual_approvals(self, counts: dict[str, int], dry_run: bool) -> None:
        """Apply jobs the operator approved from the dashboard (was REJECTED).

        Skips Rule/AI re-scoring — the human override is the decision. Uses the
        stored resume profile when present, otherwise the configured default.
        """
        list_fn = getattr(self.jobs, "list_by_status", None)
        if not callable(list_fn):
            return
        from_row = getattr(self.jobs, "job_from_row", None)
        rows = list_fn(JobStatus.APPROVED)
        if not rows:
            return
        default_profile = (
            getattr(self.cfg, "default_career_profile", None)
            or getattr(getattr(self.cfg, "profiles", None), "default", None)
            or "General"
        )
        logger.info("Manual approvals pending: %s", len(rows))
        for row in rows:
            if self._session_limit_reached():
                break
            job = (from_row(row) if callable(from_row)
                   else JobService.job_from_row(row))
            if not (job.job_description or "").strip():
                logger.warning("Approved job #%s has no JD stored — skipping "
                               "apply until re-read", job.job_id)
                continue
            self._job_seq += 1
            n = self._job_seq
            tag = f"{job.portal}:{job.job_title}".strip()
            profile = (job.selected_resume or default_profile or "General")
            score = float(job.match_score) if job.match_score is not None else 100.0
            evaluation = AIEvaluation(
                match_score=score,
                career_profile=str(profile),
                confidence=1.0,
                reason="manual dashboard approval",
                apply=True,
                provider="manual",
                model="dashboard",
            )
            self.jobs.update_status(job.job_id, JobStatus.MATCHED,
                                    match_score=score, selected_resume=str(profile))
            counts["matched"] = counts.get("matched", 0) + 1
            counts["found"] = counts.get("found", 0) + 1
            self._found = counts["found"]
            self._stage(n, "MANUAL_APPROVED", f"id={job.job_id} | {tag}")
            result = (self.apply_engine.dry_run(job, evaluation) if dry_run
                      else self.apply_engine.apply_to_job(job, evaluation))
            if result.success:
                counts["applied"] = counts.get("applied", 0) + 1
                self.stream.applied(job, dry_run)
            self._stage(n, "JOB_FINISHED",
                        "MANUAL APPROVED + "
                        + ("DRY-RUN" if dry_run else (
                            "APPLIED" if result.success else "APPLY-PENDING")))
            logger.info("Job #%s manual approval apply done success=%s dry_run=%s "
                        "| %s", n, result.success, dry_run, tag)

    def run_once(self) -> dict[str, int]:
        scan_id = self.scans.start()
        start = time.time()
        counts = {"found": 0, "rejected": 0, "matched": 0, "applied": 0,
                  "skipped": 0, "partial": 0, "failed": 0, "queued": 0}
        if not getattr(self.cfg.browser, "open_jobs", False):
            logger.warning("browser.open_jobs is OFF -- jobs will NOT be opened, "
                           "so every job will be marked Partial Data and no fit "
                           "decision will be made. Enable browser.open_jobs to let "
                           "the Rule/AI engines decide on the full JD.")
        dry_run = self.cfg.apply.mode == ApplyMode.DRY_RUN.value
        state = StateMachine(WorkflowState.STARTING)
        self.state = state  # exposed for dashboard/diagnostics
        self._job_seq = 0
        self._found = 0
        self._run_log = []   # reset per scan (prevents unbounded growth)
        self._ai_calls = 0
        self._errors = 0
        self._recoveries = 0
        self._ai_notified = False
        self._apply_session_plan()

        # Automated skip-day / off-hours: record an empty completed scan, no portals.
        plan = getattr(self, "session_plan", None)
        if (self.honor_session_windows and plan is not None
                and (getattr(plan, "skip_today", False)
                     or not getattr(plan, "portals", None))):
            logger.info("Session skipped (window=%s skip_today=%s portals=%s)",
                        getattr(plan, "window", ""), getattr(plan, "skip_today", False),
                        getattr(plan, "portals", []))
            state.to(WorkflowState.COMPLETED, "session skipped")
            self.scans.finish(scan_id, found=0, rejected=0, matched=0, applied=0,
                              portals=0, duration=time.time() - start,
                              status="SKIPPED")
            return counts

        # Dashboard manual overrides: apply APPROVED (was REJECTED) jobs first.
        try:
            self._process_manual_approvals(counts, dry_run)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Manual-approval pass failed (continuing scan): %s", exc)

        def _should_open(job) -> bool:
            # Stop opening new jobs once the human-like session budget is spent.
            if self._session_limit_reached():
                return False
            return self.rules.prefilter(job).accepted

        try:
            state.to(WorkflowState.COLLECTING, "begin scan")
            state.to(WorkflowState.SHORTLISTING, "streaming jobs as discovered")
            # EVENT-DRIVEN: each job is fully processed the instant it is found,
            # not after the whole scan. DB + CSV are written per stage.
            # The card pre-filter narrows the search space BEFORE opening: a card
            # whose title isn't a target role (e.g. CFO/finance) is not opened.
            self.collector.collect_streaming(
                lambda job: self._process_job(job, counts, dry_run),
                should_open=_should_open)
            state.to(WorkflowState.COMPLETED, "scan finished")
        except Exception as exc:  # noqa: BLE001 - scan must never crash the app
            state.to(WorkflowState.FAILED, str(exc))
            logger.exception("Scan pipeline error: %s", exc)
            self.scans.finish(scan_id, found=counts["found"],
                              rejected=counts["rejected"], matched=counts["matched"],
                              applied=counts["applied"], portals=len(self.collector.portals),
                              duration=time.time() - start, status="ERROR")
            return counts

        # Generate the end-of-scan summary CSVs too (the live ones already exist).
        self.reporter.generate_all()
        duration = time.time() - start
        try:
            self.reporter.generate_summary(runtime_seconds=duration)
        except Exception as exc:  # noqa: BLE001 - reporting must never crash a scan
            logger.warning("Portal summary generation failed: %s", exc)
        self.scans.finish(scan_id, found=counts["found"], rejected=counts["rejected"],
                          matched=counts["matched"], applied=counts["applied"],
                          portals=len(self.collector.portals),
                          duration=duration)
        self._record_session_history(counts, duration)
        # Automatic Session Summary -- always written in production (not debug-only).
        if self.diagnostics is not None and self.diagnostics.enabled:
            try:
                path = self.diagnostics.session_report(counts=counts)
                logger.info("Session report: %s", path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Session report failed: %s", exc)
        try:
            from ..reports.session_reports import write_session_reports
            avg_score = None
            try:
                conn = self.jobs.db.connect()
                row = conn.execute(
                    "SELECT AVG(match_score) FROM jobs WHERE match_score IS NOT NULL"
                ).fetchone()
                avg_score = round(row[0], 1) if row and row[0] is not None else None
            except Exception:  # noqa: BLE001
                pass
            portals = [getattr(p, "portal_name", "")
                       for p in getattr(self.collector, "portals", [])]
            write_session_reports(
                self.reporter.report_dir, counts=counts, duration=duration,
                portals=portals, ai_calls=getattr(self, "_ai_calls", 0),
                avg_score=avg_score, errors=getattr(self, "_errors", 0),
                recoveries=getattr(self, "_recoveries", 0),
                run_log_lines=self._run_log)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Production session reports failed: %s", exc)
        self._write_run_log_md(counts, time.time() - start)
        logger.info("Scan complete: %s", counts)
        return counts

    def _record_session_history(self, counts: dict, duration: float) -> None:
        """Append a per-run record to database/session_history.json so future
        runs can vary their behaviour. Never raises."""
        store = getattr(self, "session_history", None)
        if store is None:
            return
        try:
            avg_score = None
            try:
                conn = self.jobs.db.connect()
                row = conn.execute("SELECT AVG(match_score) FROM jobs WHERE "
                                   "match_score IS NOT NULL").fetchone()
                avg_score = round(row[0], 1) if row and row[0] is not None else None
            except Exception:  # noqa: BLE001
                pass
            plan = getattr(self, "session_plan", None)
            from datetime import datetime, timedelta, timezone
            end = datetime.now(timezone.utc)
            start = end - timedelta(seconds=duration)
            portals = list(getattr(plan, "portals", []) or [])
            if not portals:
                portals = [getattr(p, "portal_name", "")
                           for p in getattr(self.collector, "portals", [])]
            entry = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "runtime_seconds": round(duration, 1),
                "portal": ", ".join(p for p in portals if p),
                "jobs_searched": counts.get("found", 0) + counts.get("skipped", 0),
                "jobs_found": counts.get("found", 0),
                "jobs_opened": counts.get("found", 0) - counts.get("partial", 0),
                "jobs_matched": counts.get("matched", 0),
                "jobs_rejected": counts.get("rejected", 0),
                "jobs_applied": counts.get("applied", 0),
                "jobs_failed": counts.get("failed", 0),
                "jobs_skipped": counts.get("skipped", 0),
                "average_score": avg_score,
                "keywords": list(getattr(plan, "keywords", []) or [])[:20],
                "planned_window": getattr(plan, "window", ""),
                "planned_duration_minutes": getattr(plan, "duration_minutes", None),
                "planned_max_jobs": getattr(plan, "max_jobs", None),
            }
            store.record(entry)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Session history write failed: %s", exc)

    def _remember_good_job(self, job, evaluation) -> None:
        """Persist a high-scoring job to database/good_jobs.json. Never raises."""
        store = getattr(self, "good_jobs", None)
        if store is None:
            return
        try:
            from .learning import GOOD_JOB_SCORE
            if evaluation.match_score < GOOD_JOB_SCORE:
                return
            store.add({
                "title": job.job_title, "company": job.company,
                "location": job.location, "salary": job.salary,
                "industry": getattr(job, "company_description", "")[:120],
                "skills": list(getattr(job, "skills", []) or [])[:15],
                "responsibilities": (getattr(job, "responsibilities", "")
                                     or "")[:400],
                "keywords": list(getattr(job, "preferred_skills", []) or [])[:15],
                "reason": getattr(evaluation, "reason", "")[:300],
                "score": evaluation.match_score,
                "career_profile": evaluation.career_profile,
            })
        except Exception as exc:  # noqa: BLE001
            logger.warning("Good-job memory write failed: %s", exc)

    def _write_run_log_md(self, counts: dict, duration: float) -> None:
        """Write the full per-job stage trace + summary to a markdown file so the
        run is human-readable afterwards (explicit deliverable)."""
        from pathlib import Path
        from time import strftime
        try:
            out_dir = Path(self.reporter.report_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"run_log_{strftime('%Y%m%d-%H%M%S')}.md"
            found = counts.get("found", 0)
            # Matched already includes jobs that later applied; do not double-count.
            terminal = (counts.get("rejected", 0) + counts.get("matched", 0)
                        + counts.get("failed", 0) + counts.get("queued", 0))
            lines = [
                f"# CareerPilot Run Log — {strftime('%Y-%m-%d %H:%M:%S')}", "",
                f"Duration: {duration:.1f}s", "",
                "## Summary", "",
                f"- Found: {found}",
                f"- Matched: {counts.get('matched', 0)}",
                f"- Rejected: {counts.get('rejected', 0)}",
                f"- Failed (incl. Partial Data): {counts.get('failed', 0)}",
                f"- Applied: {counts.get('applied', 0)}",
                f"- Queued (awaiting confirmation/AI): {counts.get('queued', 0)}",
                f"- Skipped (already processed): {counts.get('skipped', 0)}",
                f"- Terminal coverage: {terminal}/{found} found jobs reached a "
                f"final state"
                + ("  ✅" if terminal >= found else "  ⚠️ some stranded"), "",
                "## Per-job stage trace", "", "```",
            ]
            lines += self._run_log or ["(no jobs processed)"]
            lines += ["```", ""]
            path.write_text("\n".join(lines))
            logger.info("Run log (markdown): %s", path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Run-log MD write failed: %s", exc)

    def _metric(self, field_name: str, by: int = 1) -> None:
        if self.diagnostics is not None:
            self.diagnostics.metrics.incr(field_name, by)

    def _status(self, **kw) -> None:
        if self.status_sink is not None:
            try:
                self.status_sink.set(**kw)
            except Exception:  # noqa: BLE001
                pass

    def _stage(self, n: int, stage: str, detail: str = "") -> None:
        """Uniform per-job execution-stage marker (provable pipeline trace)."""
        line = f"Job #{n} | {stage}" + (f" | {detail}" if detail else "")
        logger.info(line)
        self._run_log.append(line)
        self._status(job_number=n, stage=stage)

    def _process_job(self, job: Job, counts: dict[str, int], dry_run: bool) -> None:
        """Run ONE job through the entire pipeline immediately (streaming).

        Every stage commits to the DB and appends to the live CSVs as it happens,
        and every transition is logged with an explicit stage marker, so the
        job's lifecycle is fully provable and a crash loses nothing.
        """
        # Human-like session budget: once the planned job cap or time window is
        # spent, stop processing new jobs (a person ends their session).
        if self._session_limit_reached():
            counts["skipped"] = counts.get("skipped", 0) + 1
            logger.info("Session budget spent (found=%s cap=%s) -- ending "
                        "session; skipping %s", self._found,
                        getattr(self, "session_max_jobs", 0),
                        f"{job.portal}:{job.job_title}".strip())
            return

        self._job_seq += 1
        n = self._job_seq
        tag = f"{job.portal}:{job.job_title}".strip()
        try:
            # Crash recovery / AI-retry: terminal rows are skipped; retriable
            # statuses (QUEUED, PARTIAL_DATA, APPLYING, FOUND) are resumed.
            find = getattr(self.jobs, "find_existing", None)
            existing = find(job) if callable(find) else None
            if existing is None and self.jobs.exists(job):
                # Legacy / test doubles without find_existing.
                counts["skipped"] += 1
                logger.info("Job #%s SKIPPED (duplicate -- already in database) "
                            "| %s", n, tag)
                return
            if existing is not None:
                status = (existing.get("status") or "").upper()
                from ..db.services import RETRIABLE_STATUSES
                # REJECTED: skip unless title/salary/JD/etc. materially changed.
                if status == JobStatus.REJECTED.value:
                    changed = material_field_changes(existing, job)
                    if not changed:
                        counts["skipped"] += 1
                        logger.info("Job #%s SKIPPED (already REJECTED, unchanged) "
                                    "| %s", n, tag)
                        return
                    job.job_id = existing["job_id"]
                    if hasattr(self.jobs, "update_material_fields"):
                        self.jobs.update_material_fields(job.job_id, job)
                    if hasattr(self.jobs, "update_status"):
                        self.jobs.update_status(job.job_id, JobStatus.FOUND,
                                                rejection_reason=None)
                    counts["found"] += 1
                    self._found = counts["found"]
                    self._recoveries = getattr(self, "_recoveries", 0) + 1
                    self._stage(n, "REJECTED_RECHECK",
                                f"id={job.job_id} changed={','.join(changed)}")
                    logger.info("Job #%s RECHECK (was REJECTED; changed %s) | %s",
                                n, ",".join(changed), tag)
                elif status not in RETRIABLE_STATUSES:
                    counts["skipped"] += 1
                    logger.info("Job #%s SKIPPED (duplicate -- terminal status "
                                "%s already in database) | %s", n, status, tag)
                    return
                else:
                    # Retriable: reuse the existing row and continue the pipeline.
                    job.job_id = existing["job_id"]
                    counts["found"] += 1
                    self._found = counts["found"]
                    self._recoveries = getattr(self, "_recoveries", 0) + 1
                    self._stage(n, "RETRY_RESUMED",
                                f"id={job.job_id} prior_status={status}")
                    logger.info("Job #%s RETRY (prior status=%s) | %s", n, status, tag)
            else:
                self._stage(n, "CARD_DETECTED", tag)
                job.job_id = self.jobs.insert(job)          # INSERT + commit
                counts["found"] += 1
                self._found = counts["found"]
                self._metric("jobs_parsed"); self._metric("db_updates"); self._metric("csv_updates")
                self._status(portal=job.portal, job_number=n, job_title=job.job_title, db_status="inserted", csv_status="FoundJobs")
                self.stream.found(job)                       # -> FoundJobs.csv (live)
                self._stage(n, "DATABASE_UPDATED", f"id={job.job_id} (FoundJobs.csv)")

            rs = getattr(job, "read_status", "UNREAD")

            # Card pre-filter outcome: a card deemed not worth opening is a clean
            # REJECTION (a card-level open/skip decision, never a JD fit decision).
            if rs == "SKIPPED_PREFILTER":
                reason = "card pre-filter: not a target role"
                self.jobs.update_status(job.job_id, JobStatus.REJECTED,
                                        rejection_reason=reason)
                counts["rejected"] += 1
                self._metric("jobs_rejected"); self._metric("csv_updates")
                self._status(rule_decision="SKIP-OPEN", csv_status="RejectedJobs",
                             db_status="rejected")
                self.stream.rejected(job, reason)
                self._stage(n, "DECISION_COMPLETED", "REJECTED (not opened: "
                            "card pre-filter)")
                self._stage(n, "JOB_FINISHED", "REJECTED")
                return

            # HARD GATE: the Rule and AI engines decide ONLY on a fully-read job.
            # A job never opened (UNREAD) or only partially read (PARTIAL) is
            # NEVER selected/rejected-for-fit from card data -- it is marked
            # Partial Data and routed to failed_jobs.csv (never stranded).
            if rs != "COMPLETE":
                reason = _terminal_failure_reason(job)
                self.jobs.update_status(job.job_id, JobStatus.PARTIAL_DATA,
                                        rejection_reason=reason)
                self.failed_jobs.record(job.job_id, reason, retry_count=1)
                counts["partial"] = counts.get("partial", 0) + 1
                counts["failed"] = counts.get("failed", 0) + 1
                self._metric("jobs_queued")
                self._status(rule_decision="FAILED", db_status="partial_data",
                             csv_status="FailedJobs", wait_reason=reason,
                             open_job=job.job_title,
                             extracted_fields=getattr(job, "failure_detail", "")
                             or ", ".join(getattr(job, "missing_fields", [])))
                self.stream.failed(job, reason)
                self._stage(n, "DECISION_COMPLETED", f"FAILED ({reason})")
                self._stage(n, "JOB_FINISHED", "FAILED (FailedJobs.csv)")
                logger.warning("Job #%s PARTIAL DATA (%s) | read_status=%s -> "
                               "failed_jobs.csv | NOT decided from card | %s",
                               n, reason, rs, tag)
                return
            self._stage(n, "JD_READING_COMPLETED",
                        f"jd_chars={len(job.job_description or '')}")
            self._stage(n, "EXTRACTION_COMPLETED",
                        f"reading_ms={getattr(job, 'reading_ms', 0)}")
            logger.info("Job #%s fully read (jd_chars=%s) -> Rule Engine", n,
                        len(job.job_description or ""))

            rule_result = self.rules.evaluate(job)
            self._stage(n, "RULE_ENGINE_COMPLETED",
                        "PASS" if rule_result.accepted else
                        f"REJECT ({rule_result.reason.value})")
            if not rule_result.accepted:
                reason = rule_result.reason.value
                self.jobs.update_status(job.job_id, JobStatus.REJECTED,
                                        rejection_reason=reason)
                counts["rejected"] += 1
                self._metric("jobs_rejected"); self._metric("csv_updates")
                self._status(rule_decision="REJECT", csv_status="RejectedJobs", db_status="rejected")
                self.stream.rejected(job, reason)        # -> RejectedJobs.csv (live)
                self._stage(n, "DECISION_COMPLETED", f"REJECTED ({reason})")
                self._stage(n, "JOB_FINISHED", "REJECTED")
                return
            self._status(rule_decision="PASS", ai_status="scoring", csv_status="SelectedJobs")
            self.stream.selected(job)                    # -> SelectedJobs.csv (live)
            logger.info("Job #%s PASSED Rule Engine | SelectedJobs.csv", n)

            try:
                evaluation = self.ai.evaluate_job(job)
                self._ai_calls = getattr(self, "_ai_calls", 0) + 1
            except AIUnavailable:
                self.jobs.update_status(job.job_id, JobStatus.QUEUED)
                # Retriable: QUEUED status lets a future run resume this job.
                self.failed_jobs.record(job.job_id, "AI unavailable (queued for "
                                        "retry)", retry_count=1)
                self.stream.failed(job, "AI unavailable (queued for retry)")
                counts["queued"] = counts.get("queued", 0) + 1
                self._metric("jobs_queued"); self._metric("ai_failures")
                self._stage(n, "AI_COMPLETED", "SKIPPED: provider unavailable")
                self._stage(n, "JOB_FINISHED", "QUEUED (AI unavailable — will retry)")
                logger.warning("Job #%s AI UNAVAILABLE -> QUEUED "
                               "(will retry next run)", n)
                # Notify once per scan, then keep scanning -- never stop.
                if self.notifier and not self._ai_notified:
                    self._ai_notified = True
                    try:
                        from ..core.enums import NotificationType
                        self.notifier.send(
                            NotificationType.APPROVAL_REQUEST,
                            "AI provider unavailable -- jobs are being queued and "
                            "the scan is continuing. Check the Gemini model with "
                            "`python -m careerpilot.main models`.")
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("AI-unavailable notify failed: %s", exc)
                return

            # Proof the AI actually ran (provider/model/decision/confidence).
            self._stage(n, "AI_COMPLETED",
                        f"provider={getattr(evaluation, 'provider', '?')} "
                        f"model={getattr(evaluation, 'model', '?')} "
                        f"score={evaluation.match_score} "
                        f"confidence={getattr(evaluation, 'confidence', '?')} "
                        f"profile={evaluation.career_profile}")

            # Match-score gate: a low AI score is a REJECTION, not a match. This
            # is what keeps off-domain roles the Rule Engine let through (e.g.
            # an 'AI/ML Director' scored 15-20) out of MatchedJobs -- the AI and
            # the Rule Engine must agree on the final decision.
            min_match = getattr(self, "min_match_score", 0.0) or 0.0
            if min_match and evaluation.match_score < min_match:
                from ..core.enums import RejectionReason
                reason = (f"{RejectionReason.LOW_MATCH_SCORE.value} "
                          f"(score {evaluation.match_score:g} < {min_match:g})")
                self.jobs.update_status(job.job_id, JobStatus.REJECTED,
                                        match_score=evaluation.match_score,
                                        rejection_reason=reason)
                counts["rejected"] += 1
                self._metric("jobs_rejected"); self._metric("csv_updates")
                self._status(ai_status="scored", rule_decision="REJECT",
                             csv_status="RejectedJobs", db_status="rejected")
                self.stream.rejected(job, reason)
                self._stage(n, "DECISION_COMPLETED",
                            f"REJECTED (low score {evaluation.match_score:g} "
                            f"< {min_match:g})")
                self._stage(n, "JOB_FINISHED", "REJECTED")
                logger.info("Job #%s REJECTED (AI score %s < %s) | "
                            "RejectedJobs.csv | %s", n, evaluation.match_score,
                            min_match, tag)
                return

            self.jobs.update_status(job.job_id, JobStatus.MATCHED,
                                    match_score=evaluation.match_score,
                                    selected_resume=evaluation.career_profile)
            counts["matched"] += 1
            self._metric("jobs_selected"); self._metric("csv_updates")
            self._status(ai_status="scored", resume=evaluation.career_profile, csv_status="MatchedJobs", db_status="matched")
            self.stream.matched(job, evaluation.match_score,
                                evaluation.career_profile)   # -> MatchedJobs.csv
            self._remember_good_job(job, evaluation)         # learn (score>=80)
            self._stage(n, "DECISION_COMPLETED",
                        f"MATCHED (score={evaluation.match_score})")

            result = (self.apply_engine.dry_run(job, evaluation) if dry_run
                      else self.apply_engine.apply_to_job(job, evaluation))
            if result.success:
                counts["applied"] += 1
                self.stream.applied(job, dry_run)            # -> AppliedJobs.csv
                logger.info("Job #%s %s | AppliedJobs.csv", n,
                            "DRY-RUN ready" if dry_run else "APPLIED")
            else:
                status = getattr(result, "status", None)
                if status == JobStatus.QUEUED:
                    counts["queued"] = counts.get("queued", 0) + 1
                elif status == JobStatus.FAILED:
                    counts["failed"] = counts.get("failed", 0) + 1
                elif status == JobStatus.SKIPPED:
                    counts["skipped"] = counts.get("skipped", 0) + 1
            fin = "MATCHED"
            if result.success and not dry_run:
                fin = "MATCHED + APPLIED"
            elif dry_run:
                fin = "MATCHED (dry-run)"
            elif getattr(result, "status", None) is not None:
                fin = f"MATCHED ({getattr(result.status, 'value', result.status)})"
            self._stage(n, "JOB_FINISHED", fin)

            time.sleep(self.cfg.apply.delay_between_applications_seconds
                       if not dry_run else 0)

        except Exception as exc:  # noqa: BLE001 - isolate per-job failures
            reason = f"BROWSER_EXCEPTION: {type(exc).__name__}: {exc}"
            logger.warning("Job #%s FAILED (%s): %s", n, job.job_title, exc)
            self._errors = getattr(self, "_errors", 0) + 1
            if getattr(job, "job_id", None):
                self.jobs.update_status(job.job_id, JobStatus.PARTIAL_DATA,
                                        rejection_reason=reason)
                self.failed_jobs.record(job.job_id, reason, retry_count=1)
                self.stream.failed(job, reason)
                counts["failed"] = counts.get("failed", 0) + 1
