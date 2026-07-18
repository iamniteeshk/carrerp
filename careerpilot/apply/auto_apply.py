"""Auto Apply engine -- the execution layer (P010).

Coordinates: safety gate -> confidence gate -> resume selection -> cover letter
/ answers -> portal.apply() -> record result -> notify. It contains no
portal-specific or AI-specific logic of its own; it orchestrates the other
modules. Supports dry-run (stop before submit) and live (submit) via config.

Production rule: never claim APPLIED unless the portal truly submitted AND
(when require_final_confirmation) a human approved the final Submit.
"""

from __future__ import annotations

import time

from ..ai.engine import AIEngine, AIUnavailable
from ..browser.base_portal import (BasePortal, CaptchaRequired,
                                    ExternalATSRedirect, LoginRequired,
                                    OTPRequired)
from ..core.config import AppConfig
from ..core.enums import JobStatus, NotificationType
from ..core.logging_setup import get_logger
from ..core.models import AIEvaluation, ApplicationResult, Job
from ..db.services import (ApplicationService, FailedJobService, JobService)
from ..notify.telegram_service import TelegramService
from .confidence_gate import ConfidenceGate, GateDecision
from .safety_gate import ApplySafetyGate

logger = get_logger(__name__)


class AutoApplyEngine:
    def __init__(self, config: AppConfig, ai: AIEngine,
                 portals: dict[str, BasePortal], telegram: TelegramService,
                 job_service: JobService, app_service: ApplicationService,
                 failed_service: FailedJobService, profile_engine=None,
                 document_manager=None):
        self.cfg = config
        self.ai = ai
        self.portals = portals
        self.telegram = telegram
        self.jobs = job_service
        self.apps = app_service
        self.failed = failed_service
        self.profile_engine = profile_engine or config.profile_engine
        from ..core.document_manager import DocumentManager
        self.documents = document_manager or DocumentManager(self.profile_engine)
        self.safety = ApplySafetyGate(
            config.rules,
            require_preferred_location=bool(
                getattr(config.apply, "require_preferred_location", False)),
            chennai_priority=True,
        )

    def apply_to_job(self, job: Job, evaluation: AIEvaluation) -> ApplicationResult:
        """Attempt one application, honoring the confidence gate and mode."""
        profile = self.profile_engine.select(
            evaluation.career_profile, evaluation.confidence)
        portal = self.portals.get(job.portal)
        if portal is None:
            return self._fail(job, evaluation, profile, "no portal handler")

        if job.job_id and self.apps.already_applied(job.job_id):
            logger.info("Skip: already applied to job %s", job.job_id)
            self.jobs.update_status(job.job_id, JobStatus.SKIPPED)
            return self._result(job, evaluation, profile, success=False,
                                status=JobStatus.SKIPPED)

        # Deterministic safety gate (blacklist, domain, location, salary, ...).
        safety = self.safety.check(job, evaluation)
        if not safety.allowed:
            logger.info("Safety gate blocked %s: %s", job.job_title, safety.reason)
            if job.job_id:
                self.jobs.update_status(job.job_id, JobStatus.SKIPPED,
                                        rejection_reason=safety.reason)
            return self._result(job, evaluation, profile, success=False,
                                status=JobStatus.SKIPPED,
                                failure_reason=safety.reason)

        gate = ConfidenceGate(self.cfg.apply, self.cfg.ai.min_apply_score,
                              self._lifetime_applied())
        decision = gate.decide(job, evaluation, self.apps.applied_today_count())
        if not decision.proceed:
            logger.info("Gate blocked %s: %s", job.job_title, decision.reason)
            if job.job_id:
                self.jobs.update_status(job.job_id, JobStatus.SKIPPED)
            return self._result(job, evaluation, profile, success=False,
                                status=JobStatus.SKIPPED)

        if decision.needs_approval:
            self._request_approval(job, evaluation, profile, decision)
            # The approval response is handled out-of-band; we stage the job and
            # stop here rather than submitting unapproved.
            if job.job_id:
                self.jobs.update_status(job.job_id, JobStatus.QUEUED)
            return self._result(job, evaluation, profile, success=False,
                                status=JobStatus.QUEUED)

        return self._execute(portal, job, evaluation, dry_run=False)

    def dry_run(self, job: Job, evaluation: AIEvaluation) -> ApplicationResult:
        profile = self.profile_engine.select(
            evaluation.career_profile, evaluation.confidence)
        portal = self.portals.get(job.portal)
        if portal is None:
            return self._fail(job, evaluation, profile, "no portal handler")
        safety = self.safety.check(job, evaluation)
        if not safety.allowed:
            logger.info("Dry-run safety blocked %s: %s", job.job_title, safety.reason)
            if job.job_id:
                self.jobs.update_status(job.job_id, JobStatus.SKIPPED,
                                        rejection_reason=safety.reason)
            return self._result(job, evaluation, profile, success=False,
                                status=JobStatus.SKIPPED,
                                failure_reason=safety.reason, dry_run=True)
        return self._execute(portal, job, evaluation, dry_run=True)

    # ---- internal --------------------------------------------------------

    def _execute(self, portal: BasePortal, job: Job, evaluation: AIEvaluation,
                 dry_run: bool) -> ApplicationResult:
        if job.job_id:
            self.jobs.update_status(job.job_id, JobStatus.APPLYING)
        # Resolve the Career Profile (confidence-gated default fallback).
        profile = self.profile_engine.select(
            evaluation.career_profile, evaluation.confidence)
        try:
            from ..ops_dashboard.runtime import HUB
            HUB.note_profile(profile.name)
        except Exception:  # noqa: BLE001
            pass
        resume_path = self.documents.resume_for(profile)
        cover_letter = self._maybe_cover_letter(job, profile)
        answer_fn = self._make_answer_fn(profile, job)

        attempts = 0
        last_error = ""
        submitted_once = False
        while attempts <= self.cfg.apply.retry_limit:
            attempts += 1
            try:
                # Never retry after a successful submit (duplicate prevention).
                if submitted_once:
                    break
                outcome = portal.apply(
                    job, resume_path, cover_letter,
                    answer_fn=answer_fn, dry_run=dry_run,
                )
                # Live mode must never claim APPLIED unless the portal truly
                # submitted. Incomplete portal flows return submitted=False.
                if outcome.submitted and not dry_run:
                    submitted_once = True
                status = JobStatus.APPLIED if (outcome.submitted and not dry_run) else (
                    JobStatus.MATCHED if dry_run else JobStatus.QUEUED)
                # Incomplete live apply (forms filled / confirmation pending)
                # stays MATCHED or QUEUED — never APPLIED.
                if (not dry_run and not outcome.submitted
                        and "confirmation" in (outcome.note or "").lower()):
                    status = JobStatus.QUEUED
                result = self._result(
                    job, evaluation, profile,
                    success=bool(outcome.submitted and not dry_run),
                    status=status, portal_reference=outcome.portal_reference,
                    screenshot=outcome.screenshot_path,
                    cover_letter=cover_letter, dry_run=dry_run,
                    failure_reason=outcome.note or "",
                )
                self.apps.record(result)
                if job.job_id:
                    self.jobs.update_status(job.job_id, status)
                if outcome.submitted and not dry_run:
                    self._notify_success(job, evaluation, profile)
                return result

            except ExternalATSRedirect as exc:
                logger.info("External ATS for %s: %s", job.company, exc)
                if job.job_id:
                    self.jobs.update_status(job.job_id, JobStatus.MANUAL_REVIEW)
                self.telegram.send(
                    NotificationType.UNSUPPORTED_ATS,
                    f"Manual review: {job.job_title} @ {job.company} "
                    f"redirects to an external ATS.\n{job.job_url}")
                return self._result(job, evaluation, profile, success=False,
                                    status=JobStatus.MANUAL_REVIEW)

            except (LoginRequired, OTPRequired, CaptchaRequired) as exc:
                # Not retryable here -- needs a human. Pause and notify.
                ntype = (NotificationType.OTP_REQUIRED
                         if isinstance(exc, OTPRequired)
                         else NotificationType.LOGIN_REQUIRED)
                self.telegram.send(ntype,
                                   f"{job.portal}: {exc}. CareerPilot is waiting.")
                if job.job_id:
                    self.jobs.update_status(job.job_id, JobStatus.QUEUED)
                return self._result(job, evaluation, profile, success=False,
                                    status=JobStatus.QUEUED)

            except Exception as exc:  # noqa: BLE001 - transient; retry then fail
                last_error = str(exc)
                logger.warning("Apply attempt %s failed for %s: %s",
                               attempts, job.job_title, exc)
                time.sleep(min(2 ** attempts, 10))

        return self._fail(job, evaluation, profile, last_error or "max retries exceeded")

    def _make_answer_fn(self, profile, job: Job):
        """Answer screening questions: cached profile answer first, else AI."""
        def answer(question: str) -> str:
            cached = profile.cached_answer(question)
            if cached:
                return cached
            return self.ai.answer_screening_question(question, job)
        return answer

    def _maybe_cover_letter(self, job: Job, profile) -> str:
        # Prefer the profile's own cover letter file (uploaded by the portal);
        # only generate text when the profile doesn't supply one.
        if self.documents.has_own_cover_letter(profile):
            return ""
        try:
            return self.ai.generate_cover_letter(job, profile.name)
        except AIUnavailable:
            logger.warning("Cover letter skipped: AI unavailable")
            return ""

    def _lifetime_applied(self) -> int:
        # Distinct SUCCESSFUL live applications only (for first-run window).
        conn = self.apps.db.connect()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM applications "
            "WHERE dry_run=0 AND application_status='APPLIED'"
        ).fetchone()
        return row["c"] if row else 0

    def _request_approval(self, job: Job, evaluation: AIEvaluation, profile,
                          decision: GateDecision) -> None:
        self.telegram.send(
            NotificationType.APPROVAL_REQUEST,
            f"Approval needed ({decision.reason}):\n"
            f"{job.job_title} @ {job.company}\n"
            f"Score: {evaluation.match_score} | Profile: {profile.name}\n"
            f"{evaluation.reason}\n{job.job_url}")

    def _notify_success(self, job: Job, evaluation: AIEvaluation, profile) -> None:
        self.telegram.send(
            NotificationType.APPLICATION_SUBMITTED,
            f"Application Submitted\nCompany: {job.company}\n"
            f"Role: {job.job_title}\nPortal: {job.portal}\n"
            f"Profile: {profile.name}\nMatch: {evaluation.match_score}%")

    def _fail(self, job: Job, evaluation: AIEvaluation, profile,
              reason: str) -> ApplicationResult:
        logger.error("Application failed for %s: %s", job.job_title, reason)
        if job.job_id:
            self.jobs.update_status(job.job_id, JobStatus.FAILED)
            self.failed.record(job.job_id, reason, retry_count=self.cfg.apply.retry_limit)
        self.telegram.send(
            NotificationType.APPLICATION_FAILED,
            f"Application Failed\nCompany: {job.company}\n"
            f"Portal: {job.portal}\nReason: {reason}")
        return self._result(job, evaluation, profile, success=False,
                            status=JobStatus.FAILED, failure_reason=reason)

    def _result(self, job: Job, evaluation: AIEvaluation, profile, *, success: bool,
                status: JobStatus, portal_reference: str = "",
                screenshot: str = "", cover_letter: str = "",
                failure_reason: str = "", dry_run: bool = False) -> ApplicationResult:
        return ApplicationResult(
            job_id=job.job_id, success=success, status=status, portal=job.portal,
            company=job.company, resume_used=profile.name,
            resume_version=profile.resume_version,
            match_score=evaluation.match_score, portal_reference=portal_reference,
            screenshot_path=screenshot, cover_letter=cover_letter,
            failure_reason=failure_reason, dry_run=dry_run)
