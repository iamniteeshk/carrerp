"""Naukri portal automation.

Same contract as LinkedIn. Naukri's apply is usually native (no external
redirect), but it frequently shows chatbot-style screening questions that vary
per recruiter -- those are handled via answer_fn / candidate config. Selectors
marked `# COMPLETE ON LIVE DOM` need a logged-in session to finalize.
"""

from __future__ import annotations


from ..core.candidate import Candidate
from ..core.logging_setup import get_logger
from ..core.models import Job, ScreeningAnswer
from .base_portal import BasePortal, LoginRequired, ApplyOutcome, navigate
from .session import BrowserSession

logger = get_logger(__name__)

LOGIN_CHECK_URL = "https://www.naukri.com/mnjuser/homepage"


class NaukriPortal(BasePortal):
    portal_name = "Naukri"

    # COMPLETE ON LIVE DOM: results container + spinner selectors. Blank until
    # set (e.g. RESULTS_SELECTOR = "div.srp-jobtuple-wrapper"); wait_for_ready
    # falls back to load+networkidle in the meantime. No other code change needed.
    RESULTS_SELECTOR = ""
    SPINNER_SELECTOR = ""
    CAPTCHA_SELECTOR = ""
    # Logged-in feeds -- searched BEFORE keyword/category searches when enabled.
    # Naukri has no LinkedIn-style Easy Apply flag; recommended + "jobs for you"
    # style pages are the apply-friendly feeds. Easy-apply URL uses the same
    # recommended surface when distinct URLs are unavailable (deduped in plan).
    RECOMMENDED_URL = "https://www.naukri.com/mnjuser/recommendedjobs"
    # Naukri has no LinkedIn-style Easy Apply collection; the recommended feed is
    # the apply-friendly surface (deduped with RECOMMENDED_URL in the plan).
    EASY_APPLY_URL = "https://www.naukri.com/mnjuser/recommendedjobs"
    # Leave empty: Naukri homepage reloads caused refresh loops historically.
    # Broad coverage uses keyword searches (+ optional search_nationwide).
    ALL_JOBS_URL = ""
    # UNVERIFIED best-known selectors -- confirm with Visual Debug Mode and
    # override in config.yaml -> portals.naukri.
    DEFAULT_RESULTS_SELECTOR = "div.srp-jobtuple-wrapper, article.jobTuple"
    FIELD_SELECTORS = {
        "title": "a.title",
        "company": "a.comp-name, a.subTitle",
        "location": "span.locWdth, span.loc",
        "salary": "span.sal-wrap span, span.sal",
        "experience": "span.expwdth, span.exp",
        "url": "a.title",
    }

    def __init__(self, session: BrowserSession, candidate: Candidate,
                 debugger=None, parse_config: dict | None = None, humanizer=None,
                 detail_extractor=None):
        self.session = session
        self.candidate = candidate
        self.debugger = debugger
        self.humanizer = humanizer
        self.detail_extractor = detail_extractor
        pc = parse_config or {}
        self.results_selector = (pc.get("results_selector")
                                 or self.DEFAULT_RESULTS_SELECTOR)
        self.field_selectors = {**self.FIELD_SELECTORS, **(pc.get("fields") or {})}

    def ensure_logged_in(self) -> None:
        page = self.session.page
        # Only navigate to verify if we're not already on an authenticated Naukri
        # page. This is what stops the refresh loop: once we can't confirm login
        # we raise and STOP -- we never keep reloading the homepage underneath a
        # user who is trying to log in.
        if not self._on_naukri(page) or self._is_login_page(page):
            navigate(page, LOGIN_CHECK_URL, reason="verify Naukri login state")
        if "login" in page.url.lower():
            logger.warning("Naukri not authenticated (url=%s); pausing for login. "
                           "The page will NOT be reloaded while you log in.",
                           page.url)
            raise LoginRequired("Naukri session not authenticated")
        logger.info("Naukri authenticated | url=%s", page.url)

    @staticmethod
    def _on_naukri(page) -> bool:
        try:
            return "naukri.com" in (page.url or "")
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _is_login_page(page) -> bool:
        try:
            u = (page.url or "").lower()
        except Exception:  # noqa: BLE001
            return True
        return ("login" in u) or u in ("", "about:blank")

    @staticmethod
    def _slug(text: str) -> str:
        return "-".join(text.lower().split())

    # Minimum years of experience to filter at the URL level (Director-level
    # roles); narrows the search space before any card is opened. Naukri accepts
    # an `experience=<years>` query parameter on its public search URLs.
    MIN_EXPERIENCE_YEARS = 15

    def _search_url(self, keyword: str, location: str) -> str:
        # Public Naukri search URL pattern (address bar, not DOM):
        # https://www.naukri.com/<keyword-slug>-jobs-in-<location-slug>?experience=N
        kw = self._slug(keyword)
        if location:
            base = f"https://www.naukri.com/{kw}-jobs-in-{self._slug(location)}"
        else:
            base = f"https://www.naukri.com/{kw}-jobs"
        exp = getattr(self, "min_experience_years", self.MIN_EXPERIENCE_YEARS)
        return f"{base}?experience={exp}" if exp else base

    def search(self, keywords: list[str], locations: list[str],
               on_job=None, should_open=None) -> list[Job]:
        plan = self._build_search_plan(keywords, locations)
        return self._browse_plan(plan, on_job=on_job, should_open=should_open)

    def apply(self, job: Job, resume_path: str, cover_letter: str,
              answer_fn, dry_run: bool) -> ApplyOutcome:
        page = self.session.page
        navigate(page, job.job_url, reason=f"open job {job.company}")

        answers: list[ScreeningAnswer] = []
        # COMPLETE ON LIVE DOM: click "Apply". Naukri often opens a chatbot
        # drawer with one question at a time -- detect each, answer numeric/
        # dropdown from candidate config, free-text via answer_fn. Resume is
        # usually the saved profile resume; upload only if prompted.
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

        # LIVE APPLY SAFETY (v4 production): Naukri Apply / chatbot form-fill +
        # final Submit are not yet completed against live DOM. Never claim
        # submitted=True. Stop at the confirmation boundary and wait for an
        # explicit human confirmation before any real submit.
        if evidence:
            evidence.capture(page, job, "04_stop_before_apply")
        shot = self.session.screenshot(
            f"{self.session.profile_dir}/confirm_{job.source_id or 'job'}.png")
        logger.warning(
            "LIVE APPLY: Naukri apply form/submit not completed on live DOM — "
            "stopping at confirmation boundary for %s @ %s (submitted=False)",
            job.job_title, job.company)
        return ApplyOutcome(
            submitted=False, screenshot_path=shot, answers=answers,
            note="awaiting_final_confirmation: naukri_apply_incomplete")
