"""Base portal interface.

Each portal (LinkedIn, Naukri) implements this contract. Adding a new portal
or ATS later means implementing this class only -- the apply engine, rule
engine, and scheduler stay untouched (open/closed principle).

IMPORTANT -- READ BEFORE COMPLETING:
The methods below define *what* each portal must do. The concrete selectors and
exact navigation steps in the subclasses are marked with `# COMPLETE ON LIVE
DOM`. They cannot be finalized without a logged-in session against the live
site, because LinkedIn in particular serves per-user, A/B-tested markup. Run in
DRY_RUN mode and use the browser inspector to fill these in against your own
account before enabling LIVE mode.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from ..core.logging_setup import get_logger
from ..core.models import Job, ScreeningAnswer

logger = get_logger(__name__)
_nav_logger = get_logger("careerpilot.browser.navigation")


def same_url(a: str, b: str) -> bool:
    """True if two URLs point at the same page (ignoring trailing slash & fragment)."""
    def norm(u: str) -> tuple:
        s = urlsplit(u or "")
        return (s.scheme, s.netloc, s.path.rstrip("/"), s.query)
    return norm(a) == norm(b)


def navigate(page, url: str, *, reason: str, force: bool = False) -> bool:
    """Navigate only when actually needed.

    Reuses the current page if it is already on ``url`` (the human-like
    behaviour: don't reload a page you're already on). Returns True if a real
    navigation happened, False if the existing page was reused. Logs the full
    decision so navigation is always explainable in the logs.
    """
    try:
        current = page.url
    except Exception:  # noqa: BLE001
        current = ""
    if not force and same_url(current, url):
        _nav_logger.info("Reusing page (already on target) | url=%s | reason=%s",
                         url, reason)
        return False
    _nav_logger.info("Navigate started | from=%s | to=%s | reason=%s",
                     current or "(blank)", url, reason)
    page.goto(url, wait_until="domcontentloaded")
    _nav_logger.info("DOM loaded | now=%s", page.url)
    return True


def click_job_card(page, job, title_selector: str, humanizer=None,
                   timeout_ms: int = 5000) -> bool:
    """Find the job's own link on the page the user is looking at right now and
    perform a REAL, human-driven click on it: move the mouse there (curved,
    via the humanizer), hover, then click -- exactly the 'see card -> move
    mouse -> hover -> click -> open' workflow. This is a real Playwright click
    on the actual element, not page.goto(url) -- it fires trusted DOM events so
    it also works for JS-routed (SPA) card links, not only plain <a href>.

    Returns True only if a click was performed AND the page visibly changed as
    a result (proof something actually opened). Returns False if the card
    can't be found on the current page or the click led nowhere -- the caller
    should then fall back to a direct navigate() so a job is never left
    unopened just because its element wasn't locatable.
    """
    if not title_selector:
        return False
    title = (getattr(job, "job_title", "") or "").strip()
    url = getattr(job, "job_url", "") or ""
    try:
        locator = page.locator(title_selector)
        count = locator.count()
    except Exception as exc:  # noqa: BLE001
        _nav_logger.debug("Click-locate failed for selector %s: %s",
                          title_selector, exc)
        return False
    target = None
    # Prefer an exact href match -- most reliable when several cards share a
    # similar visible title.
    if url:
        for i in range(count):
            el = locator.nth(i)
            try:
                href = el.get_attribute("href") or ""
            except Exception:  # noqa: BLE001
                href = ""
            if href and (href == url or href in url or url.endswith(href)):
                target = el
                break
    if target is None and title:
        try:
            filtered = locator.filter(has_text=title)
            if filtered.count() > 0:
                target = filtered.first
        except Exception:  # noqa: BLE001
            target = None
    if target is None:
        _nav_logger.info("Click target NOT found on current page for '%s' -- "
                         "falling back to direct navigation", title)
        return False
    try:
        target.scroll_into_view_if_needed(timeout=timeout_ms)
        box = target.bounding_box()
        if not box:
            return False
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        pre_url = page.url
        if humanizer is not None and humanizer.enabled:
            humanizer.move_mouse(page, cx, cy)
            page.wait_for_timeout(humanizer.rng.randint(120, 350))
        target.hover(timeout=timeout_ms)
        page.wait_for_timeout(humanizer.rng.randint(150, 400) if humanizer
                              and humanizer.enabled else 150)
        _nav_logger.info("CLICK card '%s' at (%.0f, %.0f)", title, cx, cy)
        try:
            target.click(timeout=timeout_ms)
        except Exception as click_exc:  # noqa: BLE001 - nav can detach the frame
            _nav_logger.debug("click() raised (often just a navigating frame): "
                              "%s", click_exc)
        for _ in range(max(1, timeout_ms // 200)):
            try:
                if page.url != pre_url:
                    return True
            except Exception:  # noqa: BLE001 - page mid-navigation counts as ok
                return True
            page.wait_for_timeout(200)
        return page.url != pre_url
    except Exception as exc:  # noqa: BLE001
        _nav_logger.warning("Click failed for '%s': %s -- falling back to "
                            "direct navigation", title, exc)
        return False


def wait_for_ready(page, *, networkidle_timeout_ms: int = 8000,
                   render_settle_ms: int = 800, results_selector: str = "",
                   spinner_selector: str = "", reason: str = "") -> bool:
    """Wait until a JS page is actually USABLE, not merely DOM-parsed.

    'Navigation complete' (domcontentloaded) is not 'page ready'. This waits on
    real browser conditions, in order, each logged:
      1. full ``load`` (resources)
      2. ``networkidle`` (the XHR/fetch that render cards) -- bounded; if it
         never settles we log and proceed (deterministic, never hangs/crashes)
      3. the results container selector becomes visible (if configured)
      4. the loading spinner disappears (if configured)
      5. a small render-settle margin (configurable; 0 disables)

    Returns True if the results container was confirmed (or no selector was
    configured), False if a configured selector never appeared. No AI, no
    arbitrary fixed sleep as the primary mechanism.
    """
    _nav_logger.info("Ready-wait started | url=%s | reason=%s", page.url, reason)
    try:
        page.wait_for_load_state("load")
        _nav_logger.info("Load state: load complete | url=%s", page.url)
    except Exception as exc:  # noqa: BLE001
        _nav_logger.info("Load state 'load' not reached: %s", exc)

    try:
        page.wait_for_load_state("networkidle", timeout=networkidle_timeout_ms)
        _nav_logger.info("Network idle reached | url=%s", page.url)
    except Exception:  # noqa: BLE001 - busy sites may never fully idle
        _nav_logger.info("Network not idle within %sms; proceeding | url=%s",
                         networkidle_timeout_ms, page.url)

    confirmed = True
    if results_selector:
        try:
            page.wait_for_selector(results_selector, state="visible",
                                   timeout=networkidle_timeout_ms)
            _nav_logger.info("Results container detected | selector=%s",
                             results_selector)
        except Exception:  # noqa: BLE001
            confirmed = False
            _nav_logger.warning("Results selector NOT found within %sms | "
                                "selector=%s | url=%s (empty page or wrong "
                                "selector?)", networkidle_timeout_ms,
                                results_selector, page.url)

    if spinner_selector:
        try:
            page.wait_for_selector(spinner_selector, state="hidden",
                                   timeout=networkidle_timeout_ms)
            _nav_logger.info("Loading spinner disappeared | selector=%s",
                             spinner_selector)
        except Exception:  # noqa: BLE001
            _nav_logger.info("Spinner still present or absent | selector=%s",
                             spinner_selector)

    if render_settle_ms > 0:
        page.wait_for_timeout(render_settle_ms)  # small final paint margin
    _nav_logger.info("Page ready | url=%s | results_confirmed=%s",
                     page.url, confirmed)
    return confirmed


def human_scroll(page, passes: int = 3, settle_ms: int = 800) -> int:
    """Scroll the page in steps to trigger lazy-loading, like a human reading.

    Returns the number of scroll passes performed. Deterministic, no AI.
    """
    done = 0
    for i in range(max(0, passes)):
        try:
            page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
            if settle_ms > 0:
                page.wait_for_timeout(settle_ms)
            done += 1
            _nav_logger.info("Scrolled %s/%s | url=%s", i + 1, passes, page.url)
        except Exception as exc:  # noqa: BLE001 - scrolling must never crash flow
            _nav_logger.info("Scroll pass %s failed: %s", i + 1, exc)
            break
    return done


class BrowserState(str, Enum):
    """What the Browser Engine currently sees on screen (deterministic, no AI).

    Distinct from the workflow-level WorkflowState in core/state.py: this is the
    *page* the browser is looking at, not the overall job-hunt phase.
    """
    STARTING = "STARTING"
    LOGIN_PAGE = "LOGIN_PAGE"
    HOME_PAGE = "HOME_PAGE"
    SEARCH_PAGE = "SEARCH_PAGE"
    RESULTS_LOADING = "RESULTS_LOADING"
    RESULTS_VISIBLE = "RESULTS_VISIBLE"
    RESULTS_READY = "RESULTS_READY"
    SCROLLING = "SCROLLING"
    WAITING_FOR_NEW_RESULTS = "WAITING_FOR_NEW_RESULTS"
    END_OF_RESULTS = "END_OF_RESULTS"
    EMPTY_RESULTS = "EMPTY_RESULTS"
    OPENING_JOB = "OPENING_JOB"
    READING_JOB = "READING_JOB"
    SCROLLING_JOB = "SCROLLING_JOB"
    EXTRACTING = "EXTRACTING"
    WAITING_AI = "WAITING_AI"
    RETURNING_RESULTS = "RETURNING_RESULTS"
    JOB_DETAILS = "JOB_DETAILS"
    APPLICATION = "APPLICATION"
    CAPTCHA = "CAPTCHA"
    OTP = "OTP"
    ERROR_PAGE = "ERROR_PAGE"
    UNKNOWN = "UNKNOWN"


def _log_state(state: BrowserState, detail: str = "") -> None:
    _nav_logger.info("STATE -> %s%s", state.value, f" | {detail}" if detail else "")


def observe_state(page, *, results_selector: str = "",
                  login_url_signals: tuple = ("login", "/authwall", "/nlogin"),
                  captcha_selector: str = "") -> BrowserState:
    """Look at the current page and decide which BrowserState it is in.

    Deterministic: uses the URL and (when configured) selectors only. Never
    guesses with AI. When no results_selector is configured it cannot positively
    confirm RESULTS_VISIBLE, so it returns UNKNOWN and lets the caller proceed.
    """
    try:
        url = (page.url or "").lower()
    except Exception:  # noqa: BLE001
        return BrowserState.ERROR_PAGE
    if any(sig in url for sig in login_url_signals):
        return BrowserState.LOGIN_PAGE
    if "/checkpoint/" in url or "otp" in url:
        return BrowserState.OTP
    if captcha_selector and _has(page, captcha_selector):
        return BrowserState.CAPTCHA
    if results_selector:
        return (BrowserState.RESULTS_VISIBLE if _has(page, results_selector)
                else BrowserState.EMPTY_RESULTS)
    return BrowserState.UNKNOWN


def _has(page, selector: str) -> bool:
    try:
        return page.query_selector(selector) is not None
    except Exception:  # noqa: BLE001
        return False


def _card_text(card, selector: str | None) -> str:
    """Inner text of a child selector within a card (or the card itself)."""
    if not selector:
        return ""
    try:
        el = card.query_selector(selector)
        return (el.inner_text().strip() if el else "")
    except Exception:  # noqa: BLE001
        return ""


def _card_attr(card, selector: str | None, attr: str) -> str:
    if not selector:
        return ""
    try:
        el = card.query_selector(selector)
        return (el.get_attribute(attr) or "").strip() if el else ""
    except Exception:  # noqa: BLE001
        return ""


def _card_has(card, selector: str | None) -> bool:
    if not selector:
        return False
    try:
        return card.query_selector(selector) is not None
    except Exception:  # noqa: BLE001
        return False


def _missing_fields(batch: list) -> str:
    """Summarize which fields are empty across a batch (selector debug aid)."""
    if not batch:
        return ""
    checks = {"company": 0, "location": 0, "salary": 0}
    for j in batch:
        for f in checks:
            if not getattr(j, f, ""):
                checks[f] += 1
    miss = [f"{f}({n})" for f, n in checks.items() if n]
    return ", ".join(miss)


def _absolute_url(url: str, page) -> str:
    if not url or url.startswith("http"):
        return url
    try:
        base = urlsplit(page.url)
        if url.startswith("/"):
            return f"{base.scheme}://{base.netloc}{url}"
    except Exception:  # noqa: BLE001
        pass
    return url


def collect_incrementally(page, parse_fn, *, scroll_passes: int = 5,
                          settle_ms: int = 800, networkidle_timeout_ms: int = 8000,
                          key_fn=None, max_no_new: int = 2, debugger=None,
                          ctx: dict | None = None, results_selector: str = "",
                          humanizer=None, on_job=None, detail_fn=None,
                          should_open=None) -> list:
    """Browse like a human: read visible items, scroll, read newly loaded items,
    repeat until nothing new appears, then return the de-duplicated list.

    If ``on_job`` is given, each NEW job is handed to it the instant it is parsed
    -- before scrolling further -- so the pipeline can process it immediately
    (streaming / event-driven) instead of waiting for the whole scan. The
    callback is injected by the caller, so the Browser Engine stays decoupled
    from the Rule/AI engines.
    """
    if key_fn is None:
        key_fn = lambda j: getattr(j, "job_url", None) or getattr(j, "title", repr(j))
    ctx = ctx or {}
    dbg_on = bool(debugger and debugger.enabled)
    human_on = bool(humanizer and humanizer.enabled)
    seen: dict = {}
    no_new = 0
    _log_state(BrowserState.RESULTS_VISIBLE, f"url={page.url}")
    for i in range(max(1, scroll_passes + 1)):
        _log_state(BrowserState.RESULTS_VISIBLE, "collecting visible jobs")
        if dbg_on:
            debugger.highlight(page, results_selector, "job_card", "card")
        try:
            batch = parse_fn(page) or []
        except Exception as exc:  # noqa: BLE001 - extraction must not crash browse
            _nav_logger.warning("Extraction error on pass %s: %s", i + 1, exc)
            batch = []
        new = [j for j in batch if key_fn(j) not in seen]
        dups = len(batch) - len(new)
        for j in batch:
            seen[key_fn(j)] = j
        _nav_logger.info("Collected pass %s | visible=%s | new=%s | total=%s",
                         i + 1, len(batch), len(new), len(seen))
        if human_on and new:
            # Read the newly visible jobs before scrolling further.
            text = " ".join(f"{getattr(j, 'job_title', '')} "
                            f"{getattr(j, 'job_description', '')}" for j in new)
            read_ms = humanizer.read(page, text, label=f"{len(new)} new jobs")
            humanizer.idle_move(page)   # natural cursor drift while reading
        else:
            read_ms = 0
        # PHASE 1 is COLLECTION ONLY: we scroll and parse every card first, then
        # open/process them in phase 2. This lets us open each job in the SAME
        # visible tab (human workflow: click -> read -> next) without destroying
        # the results page mid-scroll.
        if dbg_on:
            debugger.scroll_diagnostics(page, i + 1, len(new), dups, len(seen))
            missing = _missing_fields(batch)
            mx, my = (humanizer.mouse_pos if human_on else (None, None))
            debugger.panel(page, {
                "Portal": ctx.get("portal", "?"),
                "State": BrowserState.RESULTS_VISIBLE.value,
                "Search": ctx.get("search", "?"),
                "Location": ctx.get("location", "?"),
                "Visible cards": len(batch),
                "Collected": len(seen),
                "Pass": i + 1,
                "Current Scroll": f"{debugger.scroll_pct(page)}%",
                "Reading timer": f"{read_ms}ms" if read_ms else "-",
                "Mouse": f"{int(mx)},{int(my)}" if mx is not None else "-",
                "Missing fields": missing or "none",
                "Cache": ctx.get("cache_stats", "-"),
            })
        if not new:
            no_new += 1
            if no_new >= max_no_new:
                _log_state(BrowserState.END_OF_RESULTS,
                           f"no new jobs after {no_new} passes | total={len(seen)}")
                break
        else:
            no_new = 0
        if i < scroll_passes:
            _log_state(BrowserState.SCROLLING, f"pass {i + 1}/{scroll_passes}")
            if dbg_on:
                debugger.pause(page, "before_scroll")
            try:
                if human_on:
                    humanizer.scroll_one_screen(page)   # gradual, human-like
                else:
                    _gradual_scroll(page)               # never one giant jump
            except Exception as exc:  # noqa: BLE001
                _nav_logger.info("Scroll failed: %s", exc)
                break
            _log_state(BrowserState.WAITING_FOR_NEW_RESULTS)
            try:
                page.wait_for_load_state("networkidle",
                                         timeout=networkidle_timeout_ms)
            except Exception:  # noqa: BLE001 - busy sites may never idle
                pass
            if settle_ms > 0:
                page.wait_for_timeout(settle_ms)
            if dbg_on:
                debugger.pause(page, "after_scroll")

    collected = list(seen.values())
    _nav_logger.info("Collection complete | %s unique cards | now opening each "
                     "in the same tab", len(collected))

    # PHASE 2: PROCESS each collected job like a human -- pre-filter, then open
    # it in the SAME visible tab, read the full JD, extract, and hand it to the
    # pipeline. Opening in the main tab means a human watching the browser SEES
    # each job open (no hidden background tabs) and there is no new_tab() to fail.
    if on_job is not None:
        # Remember the results listing so we can return to it after each job --
        # the requested 'open -> read -> extract -> go back -> continue'
        # workflow. Without this, only the FIRST job could ever be found and
        # clicked; every job after it would land on whatever page the previous
        # job left us on.
        results_url = page.url
        for idx, j in enumerate(collected, 1):
            # Card-stage gate (fail-open): skip opening only clearly off-domain
            # roles. Everything else is opened and judged on the full JD.
            open_it = True
            if should_open is not None:
                try:
                    open_it = bool(should_open(j))
                except Exception as exc:  # noqa: BLE001
                    _nav_logger.warning("should_open failed (opening anyway): %s",
                                        exc)
                    open_it = True
                if not open_it:
                    j.read_status = "SKIPPED_PREFILTER"
                    _nav_logger.info("Job %s/%s PRE_FILTER skip-open '%s'",
                                     idx, len(collected), getattr(j, "job_title", ""))
            if open_it and detail_fn is not None:
                _nav_logger.info("Job %s/%s PRE_FILTER open '%s' -> opening in tab",
                                 idx, len(collected), getattr(j, "job_title", ""))
                if human_on:
                    humanizer.idle_move(page)     # move mouse toward the card
                try:
                    detail_fn(j)                  # opens in SAME tab, reads, extracts
                except Exception as exc:  # noqa: BLE001 - never stop the scan
                    j.read_status = "PARTIAL"
                    j.missing_fields = [
                        f"NAVIGATION_FAILED: open failed: {type(exc).__name__}: {exc}"]
                    _nav_logger.warning("Job %s/%s open failed: %s",
                                        idx, len(collected), exc)
                # GO BACK to the results listing so the NEXT job's card can
                # actually be located and clicked (not just goto'd). Prefer real
                # browser back-navigation (preserves scroll position, most
                # human-like); if that doesn't land us back, force it.
                try:
                    if not same_url(page.url, results_url):
                        try:
                            page.go_back(wait_until="domcontentloaded")
                        except Exception as exc:  # noqa: BLE001
                            _nav_logger.debug("go_back failed: %s", exc)
                        if not same_url(page.url, results_url):
                            navigate(page, results_url,
                                    reason="return to results (fallback)",
                                    force=True)
                        if human_on:
                            humanizer.idle_move(page)
                        _nav_logger.info("Job %s/%s | returned to results page",
                                        idx, len(collected))
                except Exception as exc:  # noqa: BLE001 - never stop the scan
                    _nav_logger.warning("Return-to-results failed after job "
                                        "%s/%s: %s", idx, len(collected), exc)
            elif open_it and detail_fn is None:
                j.read_status = "UNREAD"
                j.missing_fields = [
                    "EXTRACTION_FAILED: job-open path inactive "
                    "(browser.open_jobs off or no detail reader wired)"]
                _nav_logger.warning("Job %s/%s NOT opened: job-open path is not "
                                    "active (browser.open_jobs off or no reader)",
                                    idx, len(collected))
            try:
                on_job(j)
            except Exception as exc:  # noqa: BLE001 - one job never stops browse
                _nav_logger.warning("on_job callback failed: %s", exc)
            # Human-like break after a job (occasionally "stepped away").
            if human_on:
                try:
                    humanizer.maybe_break(page)
                except Exception as exc:  # noqa: BLE001 - never stop the scan
                    _nav_logger.debug("maybe_break failed: %s", exc)

    return collected


def _gradual_scroll(page) -> None:
    """Fallback scroll when human mode is off: a few medium steps with short
    pauses rather than one full-height jump (which reads as a bot)."""
    vh = 800
    try:
        vh = page.evaluate("() => window.innerHeight") or 800
    except Exception:  # noqa: BLE001
        pass
    for step in (int(vh * 0.5), int(vh * 0.4), int(vh * 0.45)):
        try:
            page.evaluate(f"window.scrollBy(0, {step})")
            page.wait_for_timeout(350)
        except Exception:  # noqa: BLE001
            break


class LoginRequired(Exception):
    """Raised when the portal session is not authenticated."""


class OTPRequired(Exception):
    """Raised when the portal demands OTP/MFA."""


class CaptchaRequired(Exception):
    """Raised when a CAPTCHA/security challenge appears."""


class ExternalATSRedirect(Exception):
    """LinkedIn job redirects to an unsupported external ATS -> manual review."""


@dataclass
class ApplyOutcome:
    submitted: bool
    portal_reference: str = ""
    screenshot_path: str = ""
    answers: list[ScreeningAnswer] | None = None
    note: str = ""


class BasePortal(abc.ABC):
    """Contract every portal automation module must satisfy."""

    portal_name: str = "base"
    # Live-DOM selectors (config/subclass overridable). Blank -> readiness falls
    # back to load+networkidle and overlays/diagnostics simply have nothing to
    # match yet.
    RESULTS_SELECTOR: str = ""
    SPINNER_SELECTOR: str = ""
    CAPTCHA_SELECTOR: str = ""
    RECOMMENDED_URL: str = ""          # logged-in "recommended jobs" feed
    debugger = None                    # VisualDebugger | None
    humanizer = None                  # Humanizer | None
    detail_extractor = None           # JobDetailExtractor | None
    search_nationwide: bool = False
    search_include_recommended: bool = False

    def _debug_selectors(self) -> dict:
        return {"job_card": self._results_selector(),
                "spinner": self.SPINNER_SELECTOR, "captcha": self.CAPTCHA_SELECTOR}

    def _results_selector(self) -> str:
        return getattr(self, "results_selector", "") or self.RESULTS_SELECTOR

    def _build_search_plan(self, keywords: list[str],
                           locations: list[str]) -> list[tuple]:
        """Ordered plan: optional recommended feed, then LOCATION-MAJOR searches.

        Nationwide sweep is OFF by default (quality-first). Enable via
        ``search_nationwide: true`` in config rules.
        """
        plan: list[tuple] = []
        seen: set[str] = set()

        def add(label, url, search, loc):
            if url and url not in seen:
                seen.add(url)
                plan.append((label, url, search, loc))

        if self.RECOMMENDED_URL and getattr(self, "search_include_recommended",
                                            False):
            add("recommended jobs", self.RECOMMENDED_URL, "recommended", "")
        # Location-major: finish each preferred city across ALL keywords first.
        for loc in (locations or []):
            for kw in keywords:
                add(f"{kw} in {loc}", self._search_url(kw, loc), kw, loc)
        # Nationwide sweep only when explicitly enabled.
        if getattr(self, "search_nationwide", False):
            for kw in keywords:
                add(f"{kw} (all locations)", self._search_url(kw, ""), kw, "all")
        return plan

    def _search_url(self, keyword: str, location: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def _browse_plan(self, plan: list[tuple], on_job=None,
                     should_open=None) -> list[Job]:
        """Execute an ordered search plan with full readiness, incremental
        collection, state logging and (when enabled) Visual Debug Mode."""
        page = self.session.page
        cfg = self.session.manager.cfg
        dbg = self.debugger
        dbg_on = bool(dbg and dbg.enabled)
        rsel = self._results_selector()
        # Job-centric mode: open each job in its OWN tab, read the full JD,
        # extract + cache, close -- the results page is never disturbed. Gated
        # by browser.open_jobs and only when a detail extractor is wired.
        detail_fn = None
        if getattr(cfg, "open_jobs", False) and self.detail_extractor is not None:
            def _open_job_detail(job):
                # Open the job in the SAME (visible) tab the user is watching,
                # read the full JD, extract + cache. Phase-2 processing means all
                # cards for this search are already collected, so navigating the
                # page away is safe; the outer loop navigates to the next search
                # afterwards. No new_tab() -> no hidden tab, no new_tab failure.
                self.detail_extractor.open_and_extract(
                    page, job,
                    networkidle_timeout_ms=cfg.networkidle_timeout_ms,
                    render_settle_ms=cfg.render_settle_ms,
                    card_title_selector=self.field_selectors.get("title", ""))
            detail_fn = _open_job_detail
            logger.info("%s: job-centric mode ON (opening each job in the SAME "
                        "tab to read full JD)", self.portal_name)
        else:
            reason = ("browser.open_jobs is OFF" if not getattr(cfg, "open_jobs",
                      False) else "no detail extractor wired")
            logger.warning("%s: job-centric mode OFF (%s) -- jobs will NOT be "
                           "opened; every job will be Partial Data. Set "
                           "browser.open_jobs: true in config.yaml.",
                           self.portal_name, reason)
        jobs: list[Job] = []
        logger.info("%s search workflow start | %s page(s) planned | url=%s",
                    self.portal_name, len(plan), page.url)
        for label, url, search, location in plan:
            if dbg_on:
                dbg.reset_timeline()
                dbg.mark("Navigate", url)
            navigate(page, url, reason=f"{self.portal_name}: {label}")
            self._detect_challenge(page)
            if dbg_on:
                dbg.mark("DOM Ready")
                dbg.pause(page, "after_navigation")
            _log_state(BrowserState.SEARCH_PAGE, label)
            _log_state(BrowserState.RESULTS_LOADING)
            wait_for_ready(page, networkidle_timeout_ms=cfg.networkidle_timeout_ms,
                           render_settle_ms=cfg.render_settle_ms,
                           results_selector=rsel,
                           spinner_selector=self.SPINNER_SELECTOR,
                           reason=f"{self.portal_name} results: {label}")
            if dbg_on:
                dbg.mark("Network Idle / Results Ready")
            state = observe_state(page, results_selector=rsel,
                                  captcha_selector=self.CAPTCHA_SELECTOR)
            _log_state(state)
            if dbg_on:
                dbg.panel(page, {"Portal": self.portal_name, "State": state.value,
                                 "Search": search, "Location": location,
                                 "Visible cards": "...", "Collected": 0, "Pass": 0,
                                 "Current Scroll": "0%"})
                dbg.highlight(page, rsel, "job_card", "card")
            if state == BrowserState.EMPTY_RESULTS:
                logger.info("%s: no results for '%s'", self.portal_name, label)
                if dbg_on:
                    dbg.save_evidence(page, self.portal_name, [],
                                      {"state": state.value, "search": label})
                continue
            found = collect_incrementally(
                page, self._parse_result_cards,
                scroll_passes=cfg.scroll_passes, settle_ms=cfg.render_settle_ms,
                networkidle_timeout_ms=cfg.networkidle_timeout_ms,
                debugger=dbg, results_selector=rsel,
                humanizer=self.humanizer, on_job=on_job, detail_fn=detail_fn,
                should_open=should_open,
                ctx={"portal": self.portal_name, "search": search,
                     "location": location})
            # Anomaly: results were confirmed present yet nothing parsed.
            if dbg_on and state == BrowserState.RESULTS_VISIBLE and not found:
                dbg.zero_results_anomaly(page, self.portal_name,
                                         self._debug_selectors(), state.value)
            logger.info("%s page done | %s | url=%s | jobs_found=%s",
                        self.portal_name, label, page.url, len(found))
            if dbg_on:
                dbg.log_first_jobs(found)
                dbg.mark("Extraction Complete", f"{len(found)} jobs")
                dbg.save_evidence(page, self.portal_name, found,
                                  {"state": state.value, "search": label,
                                   "jobs_found": len(found)})
            _log_state(BrowserState.SEARCH_PAGE, "moving to next search")
            jobs.extend(found)
        logger.info("%s search workflow complete | total_jobs=%s",
                    self.portal_name, len(jobs))
        return jobs

    def _detect_challenge(self, page) -> None:
        """Detect CAPTCHA/OTP challenges. Default no-op; portals may override."""
        return None

    # ---- generic, config-driven card extraction -------------------------
    # Field selectors are scoped *inside* each card element. Defaults are
    # best-known public selectors but are UNVERIFIED -- confirm with Visual Debug
    # Mode (selector diagnostics) and override via config.yaml -> portals.
    FIELD_SELECTORS: dict = {}

    def _parse_result_cards(self, page) -> list[Job]:
        """Extract every currently-visible job card into Job objects using the
        configured selectors. Real machinery -- returns jobs when the selectors
        match, [] when they don't (Visual Debug Mode shows which case you're in).
        """
        sel = getattr(self, "results_selector", "") or self.RESULTS_SELECTOR
        if not sel:
            logger.info("%s: no results_selector configured -- set it in "
                        "config.yaml -> portals (use Visual Debug Mode to find it)",
                        self.portal_name)
            return []
        fields = {**self.FIELD_SELECTORS, **getattr(self, "field_selectors", {})}
        try:
            cards = page.query_selector_all(sel)
        except Exception as exc:  # noqa: BLE001
            logger.warning("%s: card query failed for %s: %s",
                           self.portal_name, sel, exc)
            return []
        jobs: list[Job] = []
        for card in cards:
            title = _card_text(card, fields.get("title"))
            url = _card_attr(card, fields.get("url") or fields.get("title"), "href")
            if not title or not url:
                continue  # never invent data; skip incomplete cards
            jobs.append(Job(
                portal=self.portal_name,
                job_title=title,
                company=_card_text(card, fields.get("company")),
                location=_card_text(card, fields.get("location")),
                salary=_card_text(card, fields.get("salary")),
                experience=_card_text(card, fields.get("experience")),
                job_url=_absolute_url(url, page),
                is_easy_apply=bool(fields.get("easy_apply")
                                   and _card_has(card, fields["easy_apply"])),
            ))
        logger.info("%s: parsed %s/%s visible cards into jobs",
                    self.portal_name, len(jobs), len(cards))
        return jobs

    def ensure_healthy(self) -> None:
        """Ensure the portal's browser is alive before use (self-healing).

        Session-backed portals restart a dead browser context here so a crash
        during long unattended operation recovers on the next scan. Default is a
        no-op for portals without a persistent browser (e.g. test fakes).
        """
        session = getattr(self, "session", None)
        if session is not None and hasattr(session, "ensure_healthy"):
            session.ensure_healthy()

    @abc.abstractmethod
    def ensure_logged_in(self) -> None:
        """Verify the session; raise LoginRequired/OTPRequired if not ready."""

    @abc.abstractmethod
    def search(self, keywords: list[str], locations: list[str]) -> list[Job]:
        """Search and return normalized, un-filtered Job objects."""

    @abc.abstractmethod
    def apply(self, job: Job, resume_path: str, cover_letter: str,
              answer_fn, dry_run: bool) -> ApplyOutcome:
        """Complete the application for ``job``.

        ``answer_fn(question) -> str`` is called for free-text screening
        questions (the AI engine), so the portal never imports AI itself.
        When ``dry_run`` is True, fill everything but stop before submit.
        """
