"""Job detail extraction -- the job-centric (not card-centric) workflow.

For each discovered job this opens the job's own page, waits for it to render,
reads it like a human (scroll + content-scaled reading time), extracts the FULL
job description and every configured field into the Job, caches it so it is
never reopened, and returns. The streaming pipeline runs this BEFORE the Rule
Engine and AI so they see the complete JD, not just the card summary.
"""

from __future__ import annotations

from .base_portal import (BrowserState, _log_state, navigate, wait_for_ready,
                           _card_text, _card_attr, _page_alive, _safe_wait_ms)
from .lifecycle import RUNTIME
from ..core.logging_setup import get_logger

logger = get_logger("careerpilot.browser.detail")

_DESIRED_FIELDS = (
    "salary", "experience", "employment_type", "company", "location",
    "responsibilities", "skills",
)
_MIN_JD_CHARS = 120


def assess_completeness(job) -> tuple:
    """Return (read_status, missing_fields) after detail extraction."""
    missing = []
    jd = (getattr(job, "job_description", "") or "").strip()
    if len(jd) < _MIN_JD_CHARS:
        missing.append(f"job_description ({len(jd)} chars, need {_MIN_JD_CHARS})")
    for f in _DESIRED_FIELDS:
        val = getattr(job, f, "")
        if isinstance(val, list):
            if not val:
                missing.append(f)
        elif not (val or "").strip():
            missing.append(f)
    status = "COMPLETE" if len(jd) >= _MIN_JD_CHARS else "PARTIAL"
    # Optional field gaps are reported only when the JD itself is incomplete.
    if status == "COMPLETE":
        return status, []
    return status, missing


DEFAULT_DETAIL_SELECTORS = {
    "naukri": {
        "container": "section.styles_job-desc-container__txpYf, .job-desc",
        "description": ("section.styles_job-desc-container__txpYf, "
                        ".dang-inner-html, .styles_JDC__dang-inner-html"),
        "title": "h1.styles_jd-header-title__rZwM1, h1.jd-header-title",
        "company": "div.styles_jd-header-comp-name__MvqAI a, a.comp-name",
        "location": "div.styles_jd-header-loc__LuP78 span, span.loc",
        "salary": "div.styles_jhc__salary__jdfEC, .salary",
        "experience": "div.styles_jhc__exp__k_giM, .exp",
        "employment_type": ".styles_details__employment",
        "responsibilities": ".styles_key-skill__GIPn_, .styles_job-desc-container__txpYf li",
        "skills": ".styles_key-skill__GIPn_ a, .styles_chip__N1HCE",
        "company_description": ".styles_about-company__text",
        "benefits": ".styles_benefits__text, .styles_other-details__TJd1x",
        "posted_date": ".styles_jhc__stat__PgY67",
        "recruiter_notes": ".styles_recruiter-details___, .recruiter-desc",
        "easy_apply": "#apply-button",
        "external_apply": "#company-site-button",
    },
    "linkedin": {
        "container": "div.jobs-description__content, div.jobs-description",
        "description": ("div.jobs-description__content, "
                        "article.jobs-description__container"),
        "title": "h1.t-24, h2.job-details-jobs-unified-top-card__job-title",
        "company": "a.job-details-jobs-unified-top-card__company-name",
        "location": "span.job-details-jobs-unified-top-card__bullet",
        "employment_type": "li.jobs-unified-top-card__job-insight",
        "responsibilities": "div.jobs-description__content ul li",
        "skills": "div.job-details-how-you-match__skills-item",
        "company_description": "section.jobs-company__box",
        "benefits": "div.jobs-description-benefits__text",
        "easy_apply": "button.jobs-apply-button",
        "external_apply": "a.jobs-apply-button--top-card",
    },
}


def _status(status_sink, **kwargs) -> None:
    if status_sink is None:
        return
    try:
        status_sink.set(**kwargs)
    except Exception:  # noqa: BLE001
        pass


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
                         card_title_selector: str = "",  # deprecated (v2.9.7+)
                         card_selector: str = "",        # deprecated (v2.9.7+)
                         results_page=None) -> object:
        """Open the job by URL (never by card click) and extract the full JD."""
        url = getattr(job, "job_url", "")
        portal = getattr(job, "portal", "")
        title = getattr(job, "job_title", "") or ""
        human_on = bool(self.humanizer and self.humanizer.enabled)
        sink = (self.diagnostics.status if self.diagnostics is not None else None)
        job_page = page
        self._job_seq += 1
        _status(sink, open_job=title, browser_state=BrowserState.OPENING_JOB.value,
                url=url, extracted_fields="-", missing_fields="-",
                rule_decision="-", ai_status="-")

        if self.cache is not None and not self.cache.needs_open(url):
            cached = self.cache.get(url) or {}
            for k, v in cached.items():
                if v and hasattr(job, k) and not getattr(job, k, ""):
                    setattr(job, k, v)
            status, missing = assess_completeness(job)
            job.read_status = status
            job.missing_fields = missing
            extracted = _extracted_summary(job)
            _status(sink, open_job=title, browser_state=BrowserState.EXTRACTING.value,
                    extracted_fields=extracted, missing_fields=", ".join(missing)
                    or "none", reading_ms=getattr(job, "reading_ms", 0))
            logger.info("Detail SKIP (cache hit) | read_status=%s | %s",
                        status, url)
            return job

        if not (url or "").strip():
            job.read_status = "PARTIAL"
            job.missing_fields = ["NAVIGATION_FAILED: job URL missing on card"]
            job.failure_detail = "NAVIGATION_FAILED: no job URL to open"
            return job

        sel = self._selectors(portal)
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                _log_state(BrowserState.OPENING_JOB, url)
                RUNTIME.set(workflow_state="URL_NAVIGATION_STARTED",
                            job_url=url, job_title=title,
                            page_url=getattr(job_page, "url", ""))
                logger.info("OPENING_JOB | URL_NAVIGATION_STARTED | %s | %s",
                            title, url)
                if self.diagnostics is not None:
                    self.diagnostics.attach(job_page)
                    self.diagnostics.recorder.navigate(url)
                try:
                    job_page.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass
                if not _page_alive(job_page):
                    raise RuntimeError("browser page closed before navigation")
                if human_on:
                    self.humanizer.idle_move(job_page)
                    _safe_wait_ms(job_page,
                                  self.humanizer.rng.randint(250, 700))
                navigate(job_page, url, reason=f"open job by URL: {title}")
                job.open_mode = "url_navigate"
                job._job_page = job_page  # noqa: SLF001
                logger.info("URL_NAVIGATION_COMPLETED | %s", url)
                RUNTIME.set(workflow_state="JOB_PAGE_READY",
                            page_url=getattr(job_page, "url", url))
                _status(sink, browser_state=BrowserState.JOB_DETAILS.value,
                        wait_reason="URL_NAVIGATION: direct goto job URL")

                if not _page_alive(job_page):
                    raise RuntimeError("browser page closed after navigation")
                wait_for_ready(job_page,
                               networkidle_timeout_ms=networkidle_timeout_ms,
                               render_settle_ms=render_settle_ms,
                               results_selector=sel.get("container", ""),
                               reason="job detail render")
                logger.info("JOB_PAGE_READY | %s", getattr(job_page, "url", url))

                _log_state(BrowserState.READING_JOB, title)
                logger.info("EXTRACTION_STARTED | %s", url)
                description = _card_text(job_page, sel.get("description"))
                logger.info("READING_STARTED | jd_chars=%s | %s",
                            len(description or ""), url)
                _status(sink, browser_state=BrowserState.READING_JOB.value,
                        reading_section="top section")
                if human_on:
                    if not description:
                        self.humanizer.idle_move(job_page)
                        _safe_wait_ms(job_page,
                                      self.humanizer.rng.randint(400, 900))
                    else:
                        _log_state(BrowserState.SCROLLING_JOB)
                        rec = (self.diagnostics.recorder
                               if self.diagnostics is not None else None)
                        summary = self.humanizer.incremental_read(
                            job_page, description, recorder=rec, status_sink=sink)
                        job.reading_ms = summary.get("total_ms", 0)
                logger.info("READING_COMPLETED | %s", url)

                _log_state(BrowserState.EXTRACTING, url)
                self._set(job, "job_title",
                          _card_text(job_page, sel.get("title"))
                          or getattr(job, "job_title", ""))
                self._set(job, "company",
                          _card_text(job_page, sel.get("company"))
                          or getattr(job, "company", ""))
                self._set(job, "location",
                          _card_text(job_page, sel.get("location"))
                          or getattr(job, "location", ""))
                self._set(job, "job_description", description)
                self._set(job, "salary", _card_text(job_page, sel.get("salary")))
                self._set(job, "experience",
                          _card_text(job_page, sel.get("experience")))
                self._set(job, "employment_type",
                          _card_text(job_page, sel.get("employment_type")))
                self._set(job, "responsibilities",
                          _card_text(job_page, sel.get("responsibilities")))
                self._set(job, "benefits", _card_text(job_page, sel.get("benefits")))
                self._set(job, "company_description",
                          _card_text(job_page, sel.get("company_description")))
                self._set(job, "posted_date",
                          _card_text(job_page, sel.get("posted_date")))
                self._set(job, "recruiter_notes",
                          _card_text(job_page, sel.get("recruiter_notes")))
                self._set(job, "raw_html", _safe_content(job_page))
                skills = _collect_list(job_page, sel.get("skills"))
                if skills:
                    job.skills = skills
                pref = _collect_list(job_page, sel.get("preferred_skills"))
                if pref:
                    job.preferred_skills = pref
                apply_href = _card_attr(job_page, sel.get("external_apply"), "href")
                if apply_href:
                    job.external_apply_url = apply_href
                    job.apply_url = apply_href
                if sel.get("easy_apply") and job_page.query_selector(sel["easy_apply"]):
                    job.is_easy_apply = True

                if self.cache is not None:
                    self.cache.put(_job_to_dict(job))

                self._record_detail(job_page, job, portal, sel)

                status, missing = assess_completeness(job)
                job.read_status = status
                job.missing_fields = missing
                extracted = _extracted_summary(job)
                logger.info("EXTRACTION_COMPLETED | read_status=%s | %s",
                            status, url)
                _status(sink, browser_state=BrowserState.EXTRACTING.value,
                        extracted_fields=extracted,
                        missing_fields=", ".join(missing) or "none",
                        reading_ms=getattr(job, "reading_ms", 0))

                if status != "COMPLETE":
                    reason = (f"EXTRACTION_FAILED: selector failure -- "
                              f"missing {', '.join(missing)}")
                    logger.warning("Detail INCOMPLETE for %s (attempt %s) | %s",
                                   url, attempt + 1, missing)
                    if attempt < max_retries:
                        continue
                    self._capture("job_detail_partial", job_page, job, portal, sel)
                    job.failure_detail = reason
                    logger.warning("Detail PARTIAL for %s after %s attempts -- %s",
                                   url, max_retries + 1, reason)
                    return job
                logger.info("Detail EXTRACTED COMPLETE | %s | jd_chars=%s | "
                            "missing_optional=%s", url, len(description or ""),
                            missing)
                return job
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                exc_name = type(exc).__name__
                if "TargetClosed" in exc_name or "closed" in str(exc).lower():
                    logger.warning("Detail extraction target closed for %s "
                                   "(attempt %s/%s): %s",
                                   url, attempt + 1, max_retries + 1, exc)
                else:
                    logger.warning("Detail extraction failed for %s (attempt %s/%s): "
                                   "%s", url, attempt + 1, max_retries + 1, exc)
        reason = (f"BROWSER_EXCEPTION: {type(last_exc).__name__}: {last_exc}"
                  if last_exc else "NAVIGATION_FAILED: unknown open error")
        capture_page = getattr(job, "_job_page", None) or job_page
        self._capture("job_detail_error", capture_page, job, portal, sel,
                      error=str(last_exc))
        job.read_status = "PARTIAL"
        job.missing_fields = [f"open/extract failed: {last_exc}"]
        job.failure_detail = reason
        _status(sink, wait_reason=reason,
                browser_state=BrowserState.ERROR_PAGE.value)
        logger.warning("Detail extraction giving up for %s -- %s", url, reason)
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


def _extracted_summary(job) -> str:
    parts = []
    for f in ("job_title", "company", "location", "salary", "experience",
              "employment_type", "job_description"):
        val = getattr(job, f, "")
        if isinstance(val, str) and val.strip():
            parts.append(f)
    if getattr(job, "recruiter_notes", ""):
        parts.append("recruiter_notes")
    if getattr(job, "skills", None):
        parts.append("skills")
    if getattr(job, "responsibilities", ""):
        parts.append("responsibilities")
    return ", ".join(parts) if parts else "none"


def _collect_list(page, selector: str | None) -> list[str]:
    if not selector:
        return []
    try:
        els = page.query_selector_all(selector)
        return [e.inner_text().strip() for e in els if e.inner_text().strip()]
    except Exception:  # noqa: BLE001
        return []


def _safe_content(page) -> str:
    try:
        return page.content()
    except Exception:  # noqa: BLE001
        return ""


def _job_to_dict(job) -> dict:
    keys = ("job_url", "job_title", "company", "location", "salary", "experience",
            "employment_type", "job_description", "responsibilities", "benefits",
            "company_description", "posted_date", "is_easy_apply", "skills",
            "preferred_skills", "apply_url", "external_apply_url",
            "recruiter_notes")
    return {k: getattr(job, k, None) for k in keys}
