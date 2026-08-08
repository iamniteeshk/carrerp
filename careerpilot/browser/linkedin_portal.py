"""LinkedIn portal automation.

Handles search, Easy Apply, and external-ATS detection. The structure is
complete; the selectors and step details marked `# COMPLETE ON LIVE DOM` must
be filled in against your logged-in LinkedIn account (see base_portal.py).

Design choices baked in:
* Easy Apply only (per config) -- external redirects -> ExternalATSRedirect.
* Never solves CAPTCHA or OTP; raises so the orchestrator can pause + notify.
"""

from __future__ import annotations

from urllib.parse import urlencode

from ..core.candidate import Candidate
from ..core.logging_setup import get_logger
from ..core.models import Job, ScreeningAnswer
from .base_portal import (BasePortal, ExternalATSRedirect, LoginRequired,
                          OTPRequired, ApplyOutcome, navigate)
from .session import BrowserSession

logger = get_logger(__name__)

JOBS_URL = "https://www.linkedin.com/jobs/search/"


class LinkedInPortal(BasePortal):
    portal_name = "LinkedIn"

    # COMPLETE ON LIVE DOM: the results container + spinner selectors. Left blank
    # so wait_for_ready falls back to load+networkidle until you set the real
    # ones (e.g. RESULTS_SELECTOR = "div.jobs-search-results-list"). Filling
    # these in needs no other code change.
    RESULTS_SELECTOR = ""
    SPINNER_SELECTOR = ""
    CAPTCHA_SELECTOR = ""
    # Logged-in feeds -- searched BEFORE keyword/category searches when enabled.
    RECOMMENDED_URL = "https://www.linkedin.com/jobs/collections/recommended/"
    EASY_APPLY_URL = "https://www.linkedin.com/jobs/search/?f_AL=true"
    ALL_JOBS_URL = "https://www.linkedin.com/jobs/"
    # UNVERIFIED best-known selectors -- confirm with Visual Debug Mode and
    # override in config.yaml -> portals.linkedin. LinkedIn serves per-user
    # A/B markup, so these especially must be checked against your own account.
    DEFAULT_RESULTS_SELECTOR = ("div.job-card-container, "
                                "li.jobs-search-results__list-item, "
                                "li.scaffold-layout__list-item, div.job-card-list")
    FIELD_SELECTORS = {
        "title": ("a.job-card-container__link, a.job-card-list__title, "
                  "a.job-card-list__title--link, "
                  ".artdeco-entity-lockup__title a, "
                  ".job-card-list__entity-lockup a"),
        "company": (".artdeco-entity-lockup__subtitle, "
                    ".job-card-container__primary-description, "
                    ".job-card-container__company-name"),
        "location": (".artdeco-entity-lockup__caption, "
                     ".job-card-container__metadata-item, "
                     "li.job-card-container__metadata-item"),
        "url": ("a.job-card-container__link, a.job-card-list__title, "
                "a.job-card-list__title--link, .artdeco-entity-lockup__title a"),
        "easy_apply": (".job-card-container__footer-item, "
                       ".job-card-list__footer-wrapper"),
    }

    def __init__(self, session: BrowserSession, candidate: Candidate,
                 easy_apply_only: bool = True, debugger=None,
                 parse_config: dict | None = None, humanizer=None, detail_extractor=None):
        self.session = session
        self.candidate = candidate
        self.easy_apply_only = easy_apply_only
        self.debugger = debugger
        self.humanizer = humanizer
        self.detail_extractor = detail_extractor
        pc = parse_config or {}
        self.results_selector = (pc.get("results_selector")
                                 or self.DEFAULT_RESULTS_SELECTOR)
        self.field_selectors = {**self.FIELD_SELECTORS, **(pc.get("fields") or {})}

    def ensure_logged_in(self) -> None:
        page = self.session.page
        # Only verify by navigating if we are not already on an authenticated
        # LinkedIn page. Once authenticated and browsing, we never revisit the
        # feed/login (session + navigation persistence).
        if not self._on_linkedin(page) or self._is_auth_wall(page):
            navigate(page, "https://www.linkedin.com/feed/",
                     reason="verify LinkedIn login state")
        # COMPLETE ON LIVE DOM: confirm the logged-in signal via the global nav
        # 'me' menu. Until then we rely on URL signals below.
        if "/checkpoint/" in page.url:
            logger.warning("LinkedIn security checkpoint detected at %s", page.url)
            raise OTPRequired("LinkedIn security checkpoint")
        if "login" in page.url or "/authwall" in page.url:
            logger.warning("LinkedIn not authenticated (url=%s); pausing for login",
                           page.url)
            raise LoginRequired("LinkedIn session not authenticated")
        self._detect_challenge(page)
        logger.info("LinkedIn authenticated | url=%s", page.url)

    @staticmethod
    def _on_linkedin(page) -> bool:
        try:
            return "linkedin.com" in (page.url or "")
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _is_auth_wall(page) -> bool:
        try:
            u = page.url or ""
        except Exception:  # noqa: BLE001
            return True
        return ("login" in u) or ("/authwall" in u) or u in ("", "about:blank")

    def _search_url(self, keyword: str, location: str) -> str:
        # Public LinkedIn jobs search URL params (address-bar query string, not
        # DOM): keywords, location, and f_AL=true for Easy Apply only.
        parts = {"keywords": keyword}
        if location:
            parts["location"] = location
        if self.easy_apply_only:
            parts["f_AL"] = "true"
        return f"{JOBS_URL}?{urlencode(parts)}"

    def search(self, keywords: list[str], locations: list[str],
               on_job=None, should_open=None) -> list[Job]:
        plan = self._build_search_plan(keywords, locations)
        return self._browse_plan(plan, on_job=on_job, should_open=should_open)

    def apply(self, job: Job, resume_path: str, cover_letter: str,
              answer_fn, dry_run: bool) -> ApplyOutcome:
        page = self.session.page
        navigate(page, job.job_url, reason=f"open job {job.company}")
        self._detect_challenge(page)

        if not job.is_easy_apply:
            # External application -> out of scope for V1 auto-apply.
            raise ExternalATSRedirect(f"{job.company}: external ATS")

        answers: list[ScreeningAnswer] = []
        # COMPLETE ON LIVE DOM: click "Easy Apply", then loop the multi-step
        # modal: upload resume_path, fill contact fields from self.candidate,
        # answer screening questions (numeric/dropdown from candidate config;
        # free-text via answer_fn). On any unmapped *knockout* question, abort
        # and return submitted=False with a note (the confidence gate decides).
        evidence = getattr(self, "apply_evidence", None)
        if evidence:
            evidence.capture(page, job, "01_opened_job")
            evidence.capture(page, job, "02_resume_ready")
            evidence.capture(page, job, "03_form_filled")

        if dry_run:
            if evidence:
                evidence.capture(page, job, "04_stop_before_apply")
            shot = self.session.screenshot(
                f"{self.session.profile_dir}/dryrun_{job.source_id or 'job'}.png")
            logger.info("DRY RUN: stopped before submit for %s @ %s",
                        job.job_title, job.company)
            return ApplyOutcome(submitted=False, screenshot_path=shot,
                                answers=answers, note="dry_run")

        # LIVE APPLY SAFETY (v4 production): Easy Apply form-fill + final Submit
        # are not yet completed against live LinkedIn DOM. Never claim
        # submitted=True. Fill what we can, reach (or simulate) the confirmation
        # boundary, then WAIT for explicit human confirmation before Submit.
        if evidence:
            evidence.capture(page, job, "04_stop_before_apply")
        shot = self.session.screenshot(
            f"{self.session.profile_dir}/confirm_{job.source_id or 'job'}.png")
        logger.warning(
            "LIVE APPLY: LinkedIn Easy Apply form/submit not completed on live "
            "DOM — stopping at confirmation boundary for %s @ %s (submitted=False)",
            job.job_title, job.company)
        return ApplyOutcome(
            submitted=False, portal_reference="", screenshot_path=shot,
            answers=answers,
            note="awaiting_final_confirmation: linkedin_easy_apply_incomplete")

    def _detect_challenge(self, page) -> None:
        url = page.url.lower()
        if "checkpoint" in url or "/uas/" in url:
            raise OTPRequired("LinkedIn checkpoint/OTP")
        # COMPLETE ON LIVE DOM: detect CAPTCHA iframe/element and raise.
        # if page.query_selector("iframe[title*='captcha']"):
        #     raise CaptchaRequired("LinkedIn CAPTCHA")
