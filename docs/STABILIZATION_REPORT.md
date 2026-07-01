# Stabilization Report — Navigation Fixes

First live run worked end-to-end (Edge launch, login persistence, scheduler,
dashboard, Telegram, reports). It exposed navigation bugs. All eight items below
are fixed at the root — no increased timeouts, no retries, no sleeps.

## 1 & 2 — LinkedIn timeout / Naukri refresh loop (same root cause)

`search()` looped over every (title, location) and called `page.goto()` to the
**same base URL every iteration** — LinkedIn re-hit the Jobs page (eventually a
`goto` timeout); Naukri re-hit the homepage every 1–3s (the refresh loop that
blocked manual login). The per-search URL was never built.

Fix: `search()` now builds ONE distinct URL per search from public query-param /
slug patterns (not DOM) and navigates only when the target differs from the
current page. Same base URL is never reloaded.

## 3 — Excessive page.goto()

New `navigate(page, url, reason)` helper in `base_portal.py` reuses the current
page when already on the target (`same_url` normalizes trailing slash/fragment).
Duplicate (title, location) pairs are de-duplicated. Arbitrary `sleep(2)` calls
removed from both portals' login/search/apply paths.

## 4 — Session + navigation persistence

`ensure_logged_in()` only navigates to verify if not already on an authenticated
page — once logged in and browsing, it never revisits feed/home/login. If login
can't be confirmed it raises `LoginRequired` and STOPS (no reload underneath the
user), which is what ends the Naukri refresh loop.

## 5 — Logging

Every navigation logs from-URL, to-URL, and reason. Search logs current URL,
title, location, jobs found, and workflow start/complete. The collector logs
health/login steps and distinguishes a human-action pause (LoginRequired / OTP /
CAPTCHA) from a real failure.

## 6 — Search performance

The cost was redundant navigation, now removed (reuse + dedupe). True
title×location coverage is preserved exactly — titles are NOT combined, because
that would change which results are returned.

## 7 — Browser stability

One Playwright instance, one persistent context per portal, alive for the whole
scan. `ensure_healthy()` restarts only when genuinely unhealthy. Portals never
open new tabs/contexts/windows (verified by grep + tests).

## 8 — Validation

`56 unit tests pass` (7 new navigation tests using a fake page that records every
goto), `doctor` PASS, compile + pyflakes + vulture clean. A live end-to-end dry
run on real sites is yours to perform (the sandbox has no live access); the
checklist is satisfied in code and unit tests. Keep `apply.mode: dry_run`.

---

## v2.1.1 — SPA page-readiness (the "instant URL hop" bug)

**Symptom:** Naukri/LinkedIn searches completed in a few hundred ms with
`jobs_found=0`, hopping URL to URL without letting pages render.

**Root cause (two parts):**
1. `navigate()` used `wait_until="domcontentloaded"` — fires when HTML is parsed,
   BEFORE the JS renders job cards. Extraction ran on an empty shell.
2. `_parse_result_cards()` is still the live-DOM stub returning `[]`, so jobs were
   0 regardless of timing.

**Fix (deterministic, no arbitrary sleep as the mechanism):** a new
`wait_for_ready()` in the Browser Engine waits, in order, for full `load`, then
`networkidle` (bounded — busy sites that never idle log and proceed, never hang),
then an optional results-container selector becoming visible, then an optional
spinner disappearing, then a small configurable paint-settle. A `human_scroll()`
helper then scrolls in steps to trigger lazy-loading. All stages are logged
(Navigate started → DOM loaded → Network idle → Results container detected →
Spinner gone → Scrolled n/m → Page ready). Tunable via `config.yaml -> browser:`
(`networkidle_timeout_ms`, `render_settle_ms`, `scroll_passes`). Proven with real
Playwright against a JS page that injects its results container after a delay.

**Honest limitation:** this makes the browser wait correctly, but jobs will stay
0 until the `RESULTS_SELECTOR` / `_parse_result_cards` live-DOM selectors are
filled in (Phase 2). Set `RESULTS_SELECTOR` per portal (no other code change) and
the wait will additionally block until real cards are visible.

---

## v2.2.0 — state-driven Browser Engine (observe → interact → collect)

Evolves the Browser Engine from navigate-and-parse into a deterministic,
state-driven browser that behaves like an experienced human, while keeping all
prior improvements (page-readiness wait, the workflow State Engine, navigation
reuse). No AI involved anywhere in the browser layer.

**New (`base_portal.py`):**
- `BrowserState` enum — the *page-level* states the engine sees: LOGIN_PAGE,
  SEARCH_PAGE, RESULTS_LOADING, RESULTS_VISIBLE, SCROLLING,
  WAITING_FOR_NEW_RESULTS, END_OF_RESULTS, EMPTY_RESULTS, CAPTCHA, OTP,
  ERROR_PAGE, ... (distinct from the workflow-level WorkflowState).
- `observe_state(page)` — deterministically confirms which state the page is in
  from URL + optional selectors (never AI). Used after each navigation to decide
  whether results are genuinely usable before extracting.
- `collect_incrementally(page, parse_fn)` — the human-like browse loop: collect
  visible jobs → scroll → wait for newly loaded jobs → collect new → repeat until
  no new jobs appear (END_OF_RESULTS), then de-duplicate and return. Handles
  infinite scroll/lazy-loading correctly.

**Logging** now reads as internal state, exactly as requested:
`STATE -> SEARCH_PAGE`, `STATE -> RESULTS_LOADING`, `STATE -> RESULTS_VISIBLE`,
`STATE -> SCROLLING`, `STATE -> WAITING_FOR_NEW_RESULTS`, `STATE -> END_OF_RESULTS`,
`STATE -> SEARCH_PAGE (moving to next search)`.

**Both portals** now: navigate → wait_for_ready → observe_state → (skip if
EMPTY_RESULTS) → collect_incrementally → next search.

**Proven** with real Playwright against a simulated infinite-scroll page: a
one-shot parse stopped at the 3 initially-rendered cards; the incremental loop
scrolled, collected the lazy-loaded cards, de-duplicated, and gathered all 7
before detecting end-of-results.

**Honest limitation (unchanged):** `_parse_result_cards()` is still the live-DOM
stub, so `collect_incrementally` returns 0 until per-portal `RESULTS_SELECTOR`
and the parser are filled in (Phase 2). The entire browse loop, state machine,
and logging are in place and tested; only the CSS extraction remains.
