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
import time
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlsplit

from ..core.logging_setup import get_logger
from .lifecycle import RUNTIME
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


@dataclass
class JobOpenResult:
    """Outcome of a real card click -- never mix with goto on success."""
    opened: bool
    mode: str = "failed"           # click_same_tab | click_new_tab | failed
    job_page: object | None = None
    results_page: object | None = None
    detail: str = ""

    def __bool__(self) -> bool:
        return self.opened


def _page_alive(page) -> bool:
    if page is None:
        return False
    try:
        checker = getattr(page, "is_closed", None)
        if checker is None:
            return True
        return not checker()
    except Exception:  # noqa: BLE001
        return False


def _safe_wait_ms(page, ms: int) -> None:
    """Pause without raising TargetClosedError if the page handle is stale."""
    if ms <= 0:
        return
    if not _page_alive(page):
        time.sleep(ms / 1000.0)
        return
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001
        time.sleep(ms / 1000.0)


def _is_detach_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    return ("target closed" in msg or "targetclosed" in name
            or "detached" in msg or "destroyed" in msg)


def _looks_like_job_page(page_url: str, job_url: str = "") -> bool:
    u = (page_url or "").lower()
    if not u or u in ("about:blank", "chrome://newtab/"):
        return False
    if job_url:
        j = job_url.lower()
        if j in u or u in j:
            return True
    return any(sig in u for sig in ("/job", "job-listing", "jobdetail", "jd-"))


def _dismiss_blocking_overlays(page) -> None:
    """Close sticky banners (e.g. Naukri 'Monthly subscriptions') that intercept clicks."""
    js = """
    () => {
      const closeWords = ['close', 'not now', 'later', 'skip', 'dismiss', 'no thanks'];
      const nodes = document.querySelectorAll(
        'button, [role="button"], a, span, div[class*="close"], [aria-label*="lose"]');
      for (const el of nodes) {
        const t = (el.innerText || el.getAttribute('aria-label') || '').toLowerCase();
        if (!t) continue;
        if (closeWords.some(w => t.includes(w)) || t.trim() === '×' || t.trim() === 'x') {
          const r = el.getBoundingClientRect();
          if (r.width > 4 && r.height > 4) { el.click(); return true; }
        }
      }
      return false;
    }
    """
    try:
        dismissed = page.evaluate(js)
        if dismissed:
            _nav_logger.info("Dismissed blocking overlay before card click")
            _safe_wait_ms(page, 350)
    except Exception as exc:  # noqa: BLE001
        _nav_logger.debug("Overlay dismiss skipped: %s", exc)


def _scroll_link_to_center(page, link) -> None:
    try:
        link.scroll_into_view_if_needed(timeout=5000)
        page.evaluate(
            "(el) => el.scrollIntoView({block: 'center', inline: 'center', "
            "behavior: 'instant'})", link)
        _safe_wait_ms(page, 250)
    except Exception as exc:  # noqa: BLE001
        _nav_logger.debug("scroll-to-center failed: %s", exc)


def _locate_card_link(page, job, card_selector: str, title_selector: str):
    """Find the clickable link INSIDE the matching job card (not page-global)."""
    title = (getattr(job, "job_title", "") or "").strip()
    url = getattr(job, "job_url", "") or ""
    if not title_selector:
        return None
    links = []
    if card_selector:
        try:
            for card in page.query_selector_all(card_selector):
                try:
                    link = card.query_selector(title_selector)
                    if link is not None:
                        links.append(link)
                except Exception:  # noqa: BLE001
                    continue
        except Exception as exc:  # noqa: BLE001
            _nav_logger.debug("Card-scoped query failed: %s", exc)
    if not links:
        try:
            locator = page.locator(title_selector)
            for i in range(locator.count()):
                links.append(locator.nth(i))
        except Exception:  # noqa: BLE001
            return None
    for link in links:
        try:
            href = (link.get_attribute("href") or "").strip()
            text = (link.inner_text() or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if url and href and (href == url or url.endswith(href) or href in url):
            return link
        if title and title.lower() in text.lower():
            return link
    return None


def _wait_for_job_open(results_page, context, pre_url: str,
                       pages_before: int, timeout_ms: int,
                       job_url: str = "") -> JobOpenResult:
    """Wait for same-tab navigation OR a new tab -- never assume which."""
    _nav_logger.info("WAITING_FOR_NAVIGATION | pre_url=%s | pages=%s",
                     pre_url, pages_before)
    deadline = time.monotonic() + (timeout_ms / 1000.0)
    while time.monotonic() < deadline:
        try:
            if len(context.pages) > pages_before:
                for p in context.pages[pages_before:]:
                    if not _page_alive(p):
                        continue
                    try:
                        p.wait_for_load_state("domcontentloaded", timeout=2000)
                    except Exception:  # noqa: BLE001
                        pass
                    p_url = getattr(p, "url", "") or ""
                    if not _looks_like_job_page(p_url, job_url):
                        _nav_logger.debug("Ignoring new tab (not a job page): %s",
                                          p_url)
                        continue
                    _nav_logger.info("CLICK_SUCCESS | mode=new_tab | url=%s", p_url)
                    return JobOpenResult(True, "click_new_tab", p, results_page,
                                         "opened in new tab")
            if _page_alive(results_page):
                cur = results_page.url
                if cur != pre_url and _looks_like_job_page(cur, job_url):
                    try:
                        results_page.wait_for_load_state("domcontentloaded",
                                                         timeout=2000)
                    except Exception:  # noqa: BLE001
                        pass
                    _nav_logger.info("CLICK_SUCCESS | mode=same_tab | url=%s",
                                     cur)
                    return JobOpenResult(True, "click_same_tab", results_page,
                                         results_page, "opened in same tab")
        except Exception as exc:  # noqa: BLE001
            if _is_detach_error(exc):
                for p in context.pages:
                    if not _page_alive(p):
                        continue
                    p_url = getattr(p, "url", "")
                    if p_url != pre_url and _looks_like_job_page(p_url, job_url):
                        _nav_logger.info("CLICK_SUCCESS | mode=recovered | url=%s",
                                         p_url)
                        same = p is results_page or p_url == getattr(
                            results_page, "url", "")
                        mode = "click_same_tab" if same else "click_new_tab"
                        rp = results_page if mode == "click_new_tab" else p
                        return JobOpenResult(True, mode, p, rp,
                                             "recovered after target closed")
            _nav_logger.debug("wait-for-open poll: %s", exc)
        time.sleep(0.15)
    _nav_logger.warning("WAITING_FOR_NAVIGATION timed out | still on %s",
                        pre_url if _page_alive(results_page) else "(closed)")
    return JobOpenResult(False, "failed", None, results_page,
                         "navigation timeout after click")


def click_job_card(page, job, title_selector: str, humanizer=None,
                   timeout_ms: int = 5000, card_selector: str = "") -> JobOpenResult:
    """Click the job card's own link (scoped to the card). Returns JobOpenResult.

    On success the caller must read/extract on ``job_page`` and must NOT also
    call ``navigate()``/``goto()`` for the same open.
    """
    title = (getattr(job, "job_title", "") or "").strip()
    job_url = getattr(job, "job_url", "") or ""
    if not title_selector:
        return JobOpenResult(False, "failed", None, page, "no title selector")
    link = _locate_card_link(page, job, card_selector, title_selector)
    if link is None:
        _nav_logger.info("Click target NOT found on current page for '%s'", title)
        return JobOpenResult(False, "failed", None, page,
                             "card link not found on results page")
    if not _page_alive(page):
        return JobOpenResult(False, "failed", None, page, "results page closed")
    try:
        context = page.context
        pages_before = len(context.pages)
        pre_url = page.url
        _dismiss_blocking_overlays(page)
        _scroll_link_to_center(page, link)
        box = link.bounding_box()
        if not box:
            return JobOpenResult(False, "failed", None, page,
                                 "card link not visible (no bounding box)")
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        if humanizer is not None and humanizer.enabled:
            humanizer.move_mouse(page, cx, cy)
            _safe_wait_ms(page, humanizer.rng.randint(120, 350))
        try:
            link.hover(timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001
            _nav_logger.debug("hover failed (continuing): %s", exc)
        _safe_wait_ms(page, humanizer.rng.randint(150, 450) if humanizer
                      and humanizer.enabled else 150)
        _nav_logger.info("CLICK_STARTED | card '%s' at (%.0f, %.0f)", title, cx, cy)
        clicked = False
        for attempt in range(2):
            try:
                # no_wait_after: we detect navigation ourselves -- avoids
                # TargetClosedError when Playwright's auto-wait races SPA nav.
                link.click(timeout=timeout_ms, no_wait_after=True)
                clicked = True
                _nav_logger.info("CLICK_COMPLETED | '%s'", title)
                break
            except Exception as click_exc:  # noqa: BLE001
                msg = str(click_exc).lower()
                if attempt == 0 and ("intercept" in msg or "pointer" in msg):
                    _nav_logger.warning(
                        "POINTER_INTERCEPTED on '%s' -- dismissing overlay, "
                        "re-centering card, retrying click", title)
                    _dismiss_blocking_overlays(page)
                    _scroll_link_to_center(page, link)
                    _safe_wait_ms(page, 400)
                    continue
                if _is_detach_error(click_exc):
                    _nav_logger.info("CLICK_COMPLETED | detach during navigation "
                                     "| %s", click_exc)
                    clicked = True
                    break
                _nav_logger.warning("Click failed for '%s': %s", title,
                                    click_exc)
                return JobOpenResult(False, "failed", None, page, str(click_exc))
        if not clicked:
            return JobOpenResult(False, "failed", None, page, "click not performed")
        return _wait_for_job_open(page, context, pre_url, pages_before,
                                  timeout_ms, job_url=job_url)
    except Exception as exc:  # noqa: BLE001
        _nav_logger.warning("Click failed for '%s': %s", title, exc)
        return JobOpenResult(False, "failed", None, page, str(exc))


def return_to_results(results_page, job_page, results_url: str, *,
                      open_mode: str, humanizer=None) -> None:
    """Return to the results listing without destroying the browser context."""
    _nav_logger.info("RETURNING_TO_RESULTS | mode=%s", open_mode)
    if open_mode == "click_new_tab":
        if _page_alive(job_page) and job_page is not results_page:
            try:
                job_page.close()
                _nav_logger.info("Closed job tab (results page unchanged)")
            except Exception as exc:  # noqa: BLE001
                _nav_logger.debug("job tab close: %s", exc)
        if _page_alive(results_page):
            try:
                results_page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass
        _nav_logger.info("RESULTS_READY | url=%s", getattr(results_page, "url", ""))
        return
    if not _page_alive(results_page):
        _nav_logger.warning("RETURNING_TO_RESULTS aborted -- results page closed")
        return
    if same_url(results_page.url, results_url):
        _nav_logger.info("RESULTS_READY | already on results")
        return
    try:
        results_page.go_back(wait_until="domcontentloaded")
    except Exception as exc:  # noqa: BLE001
        _nav_logger.debug("go_back failed: %s", exc)
    if not same_url(results_page.url, results_url):
        navigate(results_page, results_url,
                 reason="return to results (fallback)", force=True)
    if humanizer is not None and humanizer.enabled:
        humanizer.idle_move(results_page)
    _nav_logger.info("RESULTS_READY | url=%s", results_page.url)


def click_job_card_legacy(page, job, title_selector: str, humanizer=None,
                          timeout_ms: int = 5000) -> bool:
    return bool(click_job_card(page, job, title_selector, humanizer, timeout_ms))


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
    RUNTIME.set(workflow_state="PHASE1_COLLECTION_COMPLETE",
                page_url=getattr(page, "url", ""))
    _nav_logger.info("PHASE1_COLLECTION_COMPLETE | %s unique job URLs collected",
                     len(collected))

    # PHASE 2: evaluate each collected URL via direct navigation (no card click,
    # no go_back, no dependency on the search results page staying open).
    if on_job is not None and collected:
        RUNTIME.set(workflow_state="PHASE2_EVALUATE_STARTED")
        _nav_logger.info("PHASE2_EVALUATE_STARTED | %s URLs to open",
                         len(collected))
        for idx, j in enumerate(collected, 1):
            job_url = getattr(j, "job_url", "") or ""
            RUNTIME.set(workflow_state="PHASE2_URL_OPEN",
                        job_url=job_url,
                        job_title=getattr(j, "job_title", ""),
                        job_id=str(getattr(j, "job_id", "") or ""),
                        page_url=getattr(page, "url", ""))
            _nav_logger.info("CARD_DETECTED | %s/%s | %s | %s",
                             idx, len(collected), getattr(j, "job_title", ""),
                             job_url)
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
                _nav_logger.info("URL_OPEN | %s/%s | %s",
                                 idx, len(collected), job_url)
                if human_on:
                    humanizer.idle_move(page)
                try:
                    detail_fn(j)
                except Exception as exc:  # noqa: BLE001 - never stop the scan
                    j.read_status = "PARTIAL"
                    j.missing_fields = [
                        f"NAVIGATION_FAILED: {type(exc).__name__}: {exc}"]
                    j.failure_detail = (
                        f"NAVIGATION_FAILED: URL open failed at evaluate phase: "
                        f"{type(exc).__name__}: {exc}")
                    _nav_logger.warning("Job %s/%s URL open failed: %s",
                                        idx, len(collected), exc)
                _nav_logger.info("NEXT_JOB | finished %s/%s | %s",
                                 idx, len(collected),
                                 getattr(j, "job_title", ""))
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
        _nav_logger.info("PHASE2_EVALUATE_COMPLETE | %s URLs processed",
                         len(collected))
        RUNTIME.set(workflow_state="PHASE2_EVALUATE_COMPLETE")

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
        # URL-based evaluation: goto each collected job URL directly (v2.9.7).
        detail_fn = None
        if getattr(cfg, "open_jobs", False) and self.detail_extractor is not None:
            def _open_job_detail(job):
                self.detail_extractor.open_and_extract(
                    page, job,
                    networkidle_timeout_ms=cfg.networkidle_timeout_ms,
                    render_settle_ms=cfg.render_settle_ms)
            detail_fn = _open_job_detail
            logger.info("%s: URL-based job evaluation ON (goto each job URL, "
                        "no card clicks)", self.portal_name)
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
            logger.info("SEARCH_STARTED | %s | location=%s | url=%s",
                        search, location or "(any)", url)
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
            if state != BrowserState.EMPTY_RESULTS:
                _nav_logger.info("RESULTS_READY | %s | %s", label, page.url)
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
