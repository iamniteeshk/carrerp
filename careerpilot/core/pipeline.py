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
from ..core.models import Job
from ..core.state import StateMachine, WorkflowState
from ..db.services import FailedJobService
from ..db.services import JobService, ScanService
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
        self.stream = StreamingCSVReporter(reporter.report_dir)
        self._job_seq = 0
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

    def run_once(self) -> dict[str, int]:
        scan_id = self.scans.start()
        start = time.time()
        counts = {"found": 0, "rejected": 0, "matched": 0, "applied": 0,
                  "skipped": 0, "partial": 0}
        if not getattr(self.cfg.browser, "open_jobs", False):
            logger.warning("browser.open_jobs is OFF -- jobs will NOT be opened, "
                           "so every job will be marked Partial Data and no fit "
                           "decision will be made. Enable browser.open_jobs to let "
                           "the Rule/AI engines decide on the full JD.")
        dry_run = self.cfg.apply.mode == ApplyMode.DRY_RUN.value
        state = StateMachine(WorkflowState.STARTING)
        self.state = state  # exposed for dashboard/diagnostics
        self._job_seq = 0

        try:
            state.to(WorkflowState.COLLECTING, "begin scan")
            state.to(WorkflowState.SHORTLISTING, "streaming jobs as discovered")
            # EVENT-DRIVEN: each job is fully processed the instant it is found,
            # not after the whole scan. DB + CSV are written per stage.
            # The card pre-filter narrows the search space BEFORE opening: a card
            # whose title isn't a target role (e.g. CFO/finance) is not opened.
            self.collector.collect_streaming(
                lambda job: self._process_job(job, counts, dry_run),
                should_open=lambda job: self.rules.prefilter(job).accepted)
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
        self.scans.finish(scan_id, found=counts["found"], rejected=counts["rejected"],
                          matched=counts["matched"], applied=counts["applied"],
                          portals=len(self.collector.portals),
                          duration=time.time() - start)
        # Automatic Session Summary (#7) -- the first doc to read after a run.
        if self.diagnostics is not None and self.diagnostics.enabled:
            try:
                path = self.diagnostics.session_report(counts=counts)
                logger.info("Session report: %s", path)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Session report failed: %s", exc)
        self._write_run_log_md(counts, time.time() - start)
        logger.info("Scan complete: %s", counts)
        return counts

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
            terminal = (counts.get("rejected", 0) + counts.get("matched", 0)
                        + counts.get("failed", 0))
            lines = [
                f"# CareerPilot Run Log — {strftime('%Y-%m-%d %H:%M:%S')}", "",
                f"Duration: {duration:.1f}s", "",
                "## Summary", "",
                f"- Found: {found}",
                f"- Matched: {counts.get('matched', 0)}",
                f"- Rejected: {counts.get('rejected', 0)}",
                f"- Failed (incl. Partial Data): {counts.get('failed', 0)}",
                f"- Applied (dry-run ready): {counts.get('applied', 0)}",
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
        self._job_seq += 1
        n = self._job_seq
        tag = f"{job.portal}:{job.job_title}".strip()
        try:
            # Crash recovery: a job already in the DB (this or a previous run) is
            # skipped, so a restart continues where it left off.
            if self.jobs.exists(job):
                counts["skipped"] += 1
                logger.info("Job #%s SKIPPED (duplicate -- same job already seen "
                            "this run or in the database from a prior run) | %s",
                            n, tag)
                return

            self._stage(n, "CARD_DETECTED", tag)
            job.job_id = self.jobs.insert(job)          # INSERT + commit
            counts["found"] += 1
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
            except AIUnavailable:
                self.jobs.update_status(job.job_id, JobStatus.QUEUED)
                # Terminal record so the job isn't stranded; QUEUED status still
                # lets a future run retry it.
                self.failed_jobs.record(job.job_id, "AI unavailable (queued for "
                                        "retry)", retry_count=1)
                self.stream.failed(job, "AI unavailable (queued for retry)")
                counts["failed"] = counts.get("failed", 0) + 1
                self._metric("jobs_queued"); self._metric("ai_failures")
                self._stage(n, "AI_COMPLETED", "SKIPPED: provider unavailable")
                self._stage(n, "JOB_FINISHED", "FAILED (AI unavailable)")
                logger.warning("Job #%s AI UNAVAILABLE -> QUEUED + failed_jobs.csv "
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
            self._stage(n, "DECISION_COMPLETED",
                        f"MATCHED (score={evaluation.match_score})")

            result = (self.apply_engine.dry_run(job, evaluation) if dry_run
                      else self.apply_engine.apply_to_job(job, evaluation))
            if result.success:
                counts["applied"] += 1
                self.stream.applied(job, dry_run)            # -> AppliedJobs.csv
                logger.info("Job #%s %s | AppliedJobs.csv", n,
                            "DRY-RUN ready" if dry_run else "APPLIED")
            self._stage(n, "JOB_FINISHED", "MATCHED" + (" + APPLIED"
                        if result.success and not dry_run else
                        " (dry-run)" if dry_run else ""))

            time.sleep(self.cfg.apply.delay_between_applications_seconds
                       if not dry_run else 0)

        except Exception as exc:  # noqa: BLE001 - isolate per-job failures
            reason = f"BROWSER_EXCEPTION: {type(exc).__name__}: {exc}"
            logger.warning("Job #%s FAILED (%s): %s", n, job.job_title, exc)
            if getattr(job, "job_id", None):
                self.jobs.update_status(job.job_id, JobStatus.PARTIAL_DATA,
                                        rejection_reason=reason)
                self.failed_jobs.record(job.job_id, reason, retry_count=1)
                self.stream.failed(job, reason)
                counts["failed"] = counts.get("failed", 0) + 1
