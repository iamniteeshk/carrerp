"""Job detail extraction -- the job-centric (not card-centric) workflow.

For each discovered job this opens the job's own page, waits for it to render,
reads it like a human (scroll + content-scaled reading time), extracts the FULL
job description and every configured field into the Job, caches it so it is
never reopened, and returns. The streaming pipeline runs this BEFORE the Rule
Engine and AI so they see the complete JD, not just the card summary.

Selectors are config-driven (config.yaml -> portals.<portal>.detail). The
defaults are best-known but UNVERIFIED -- confirm with Visual Debug Mode against
the live page. When a selector matches nothing, the corresponding field is left
as it was (card value), never invented.

Browser-only: imports no Rule/AI code. Deterministic. Never crashes the scan.
"""

from __future__ import annotations

from .base_portal import (BrowserState, _log_state, navigate, wait_for_ready,
                           _card_text, _card_attr, click_job_card)
from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.browser.detail")

# A job is COMPLETE for decision purposes when it has a substantive JD; the
# Rule/AI engines only ever decide on a COMPLETE job. Optional fields are
# recorded as missing but do not block a decision.
_DESIRED_FIELDS = ("salary", "experience", "employment_type", "company")
_MIN_JD_CHARS = 120


def assess_completeness(job) -> tuple:
    """Return (read_status, missing_fields) after detail extraction.

    COMPLETE -> substantive JD present (engines may decide).
    PARTIAL  -> JD missing/too short (never auto-decided; marked Partial Data).
    """
    missing = []
    jd = (getattr(job, "job_description", "") or "").strip()
    if len(jd) < _MIN_JD_CHARS:
        missing.append("job_description")
    for f in _DESIRED_FIELDS:
        if not (getattr(job, f, "") or "").strip():
            missing.append(f)
    status = "COMPLETE" if len(jd) >= _MIN_JD_CHARS else "PARTIAL"
    return status, missing

# UNVERIFIED best-known detail-page field selectors per portal. Override in
# config.yaml -> portals.<portal>.detail.
DEFAULT_DETAIL_SELECTORS = {
    "naukri": {
        "container": "section.styles_job-desc-container__txpYf, .job-desc",
        "description": "section.styles_job-desc-container__txpYf, .dang-inner-html",
        "salary": "div.styles_jhc__salary__jdfEC, .salary",
        "experience": "div.styles_jhc__exp__k_giM, .exp",
        "employment_type": ".styles_details__employment",
        "company_description": ".styles_about-company__text",
        "posted_date": ".styles_jhc__stat__PgY67",
        "easy_apply": "#apply-button",
        "external_apply": "#company-site-button",
    },
    "linkedin": {
        "container": "div.jobs-description__content, div.jobs-description",
        "description": "div.jobs-description__content, article.jobs-description__container",
        "employment_type": "li.jobs-unified-top-card__job-insight",
        "company_description": "section.jobs-company__box",
        "easy_apply": "button.jobs-apply-button",
    },
}


class JobDetailExtractor:
    """Opens and reads one job page at a time, human-like, AI-free."""

    def __init__(self, debugger=None, humanizer=None, job_cache=None,
                 detail_config: dict | None = None, diagnostics=None):
        self.debugger = debugger
        self.humanizer = humanizer
        self.cache = job_cache
        self.detail_config = detail_config or {}
        self.diagnostics = diagnostics
        self._job_seq = 0

    def _selectors(self, portal: str) -> dict:
        base = dict(DEFAULT_DETAIL_SELECTORS.get(portal.lower(), {}))
        base.update(self.detail_config.get(portal.lower(), {}).get("detail", {}))
        return base

    def open_and_extract(self, page, job, *, networkidle_timeout_ms: int = 8000,
                         render_settle_ms: int = 800, max_retries: int = 1,
                         card_title_selector: str = "") -> object:
        """Open the job page, read it, fill job in place, cache it, return job.

        If the job is already cached and unchanged, skips the open entirely
        (crash recovery / no-rework). On selector/render failure it RETRIES,
        then captures a failure-evidence bundle, logs the exact reason, and
        continues with the card-level data -- the scan never stops, and the
        feature is never silently disabled.
        """
        url = getattr(job, "job_url", "")
        portal = getattr(job, "portal", "")
        human_on = bool(self.humanizer and self.humanizer.enabled)
        self._job_seq += 1

        # Cache: never reopen an unchanged job.
        if self.cache is not None and not self.cache.needs_open(url):
            cached = self.cache.get(url) or {}
            for k, v in cached.items():
                if v and hasattr(job, k) and not getattr(job, k, ""):
                    setattr(job, k, v)
            # IMPORTANT: assess completeness from the CACHED data and set
            # read_status. Without this, a cache hit leaves read_status at its
            # UNREAD default and the pipeline would wrongly mark an already-read
            # job as Partial Data on every re-encounter.
            status, missing = assess_completeness(job)
            job.read_status = status
            job.missing_fields = missing
            logger.info("Detail SKIP (cache hit) | read_status=%s | %s",
                        status, url)
            return job

        sel = self._selectors(portal)
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                _log_state(BrowserState.OPENING_JOB, url)
                logger.info("STAGE OPENING_JOB | %s | %s", getattr(job,
                            "job_title", ""), url)
                if self.diagnostics is not None:
                    self.diagnostics.attach(page)
                    self.diagnostics.recorder.navigate(url)
                # Bring the job tab to the foreground so a human watching the
                # browser actually SEES each job open (not a hidden background
                # tab). Best-effort; never fatal.
                try:
                    page.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass
                # THE REQUESTED WORKFLOW: try a REAL click on the card's own
                # link first (move mouse -> hover -> click) -- not a raw
                # page.goto(). Only fall back to direct navigation if the card
                # element can't be found on the page the user is looking at
                # (e.g. it scrolled out of a virtualized list).
                clicked = False
                if card_title_selector:
                    clicked = click_job_card(
                        page, job, card_title_selector,
                        humanizer=self.humanizer if human_on else None)
                if clicked:
                    logger.info("STAGE JOB_OPENED | %s | via REAL CLICK "
                               "(move -> hover -> click)", url)
                else:
                    if human_on:
                        self.humanizer.idle_move(page)    # natural cursor drift
                    logger.info("STAGE JOB_OPENED (fallback) | %s | direct "
                               "navigate -- card link not clickable on this "
                               "page", url)
                    navigate(page, url,
                             reason=f"open job: {getattr(job,'job_title','')}")
                wait_for_ready(page,
                               networkidle_timeout_ms=networkidle_timeout_ms,
                               render_settle_ms=render_settle_ms,
                               results_selector=sel.get("container", ""),
                               reason="job detail render")

                _log_state(BrowserState.READING_JOB, getattr(job, "job_title", ""))
                description = _card_text(page, sel.get("description"))
                logger.info("STAGE JD_READING_STARTED | jd_chars=%s | %s",
                            len(description or ""), url)
                if human_on and description:
                    _log_state(BrowserState.SCROLLING_JOB)
                    rec = (self.diagnostics.recorder
                           if self.diagnostics is not None else None)
                    sink = (self.diagnostics.status
                            if self.diagnostics is not None else None)
                    summary = self.humanizer.incremental_read(
                        page, description, recorder=rec, status_sink=sink)
                    job.reading_ms = summary.get("total_ms", 0)
                logger.info("STAGE JD_READING_COMPLETED | %s", url)

                _log_state(BrowserState.EXTRACTING, url)
                self._set(job, "job_description", description)
                self._set(job, "salary", _card_text(page, sel.get("salary")))
                self._set(job, "experience", _card_text(page, sel.get("experience")))
                self._set(job, "employment_type",
                          _card_text(page, sel.get("employment_type")))
                self._set(job, "company_description",
                          _card_text(page, sel.get("company_description")))
                self._set(job, "posted_date",
                          _card_text(page, sel.get("posted_date")))
                self._set(job, "raw_html", _safe_content(page))
                if sel.get("external_apply"):
                    self._set(job, "external_apply_url",
                              _card_attr(page, sel.get("external_apply"), "href"))

                if self.cache is not None:
                    self.cache.put(_job_to_dict(job))

                # Job Detail Recorder (#2): save the opened job's evidence so the
                # parser can be improved later without revisiting the site.
                self._record_detail(page, job, portal, sel)

                status, missing = assess_completeness(job)
                job.read_status = status
                job.missing_fields = missing
                if status != "COMPLETE":
                    # Incomplete read: retry, then mark Partial Data + evidence.
                    logger.warning("Detail INCOMPLETE for %s (attempt %s) | "
                                   "missing=%s", url, attempt + 1, missing)
                    if attempt < max_retries:
                        continue
                    self._capture("job_detail_partial", page, job, portal, sel)
                    logger.warning("Detail PARTIAL for %s after %s attempts -- "
                                   "marking Partial Data (never auto-decided)",
                                   url, max_retries + 1)
                    return job
                logger.info("Detail EXTRACTED COMPLETE | %s | jd_chars=%s | "
                            "missing_optional=%s", url, len(description or ""),
                            missing)
                return job
            except Exception as exc:  # noqa: BLE001 - one job never stops the scan
                last_exc = exc
                logger.warning("Detail extraction failed for %s (attempt %s/%s): "
                               "%s", url, attempt + 1, max_retries + 1, exc)
        # Exhausted retries via exception: evidence + Partial Data (never card-only).
        self._capture("job_detail_error", page, job, portal, sel,
                      error=str(last_exc))
        job.read_status = "PARTIAL"
        job.missing_fields = ["job_description"]
        logger.warning("Detail extraction giving up for %s -- marking Partial "
                       "Data; the decision engines will NOT use card-only data",
                       url)
        return job

    def _record_detail(self, page, job, portal: str, sel: dict) -> None:
        if self.diagnostics is None or not self.diagnostics.enabled:
            return
        folder = (self.diagnostics.base_dir / "session" / portal.lower()
                  / "jobs" / f"job_{self._job_seq:03d}")
        self.diagnostics.export(
            page, folder, selectors=sel, parsed=[job],
            meta={"portal": portal, "job_title": getattr(job, "job_title", ""),
                  "job_url": getattr(job, "job_url", ""),
                  "stage": "job_detail"})

    def _capture(self, kind: str, page, job, portal: str, sel: dict,
                 error: str = "") -> None:
        if self.diagnostics is None:
            return
        self.diagnostics.capture_failure(
            kind, page, selectors=sel, parsed=[job],
            context={"portal": portal, "url": getattr(job, "job_url", ""),
                     "job": getattr(job, "job_title", ""), "error": error})

    @staticmethod
    def _set(job, attr: str, value) -> None:
        if value and hasattr(job, attr):
            setattr(job, attr, value)


def _safe_content(page) -> str:
    try:
        return page.content()
    except Exception:  # noqa: BLE001
        return ""


def _job_to_dict(job) -> dict:
    keys = ("job_url", "job_title", "company", "location", "salary", "experience",
            "employment_type", "job_description", "company_description",
            "posted_date", "is_easy_apply")
    return {k: getattr(job, k, None) for k in keys}
