# CareerPilot v2.9.2 — Real Click Fix (the actual root cause of "never opens a job")

You reported: *"it browses every job on the main page but it does not click a
single job description to see the match."* You were right, and it wasn't a live
DOM/selector issue -- it was a real bug in the code. Found it, fixed it, proved
it with real Playwright click-event instrumentation. No pause, no argument.

## Root cause

Every previous release ("open a job") actually meant `page.goto(job_url)` -- a
raw browser navigation. There was **never an actual DOM click** anywhere in the
pipeline. The humanizer has had a `hover_then_click()` method since early
versions, but grepping the entire codebase confirms it was **never called by
anything** -- dead code. Every prompt from v2.8.5 onward explicitly asked for
"move mouse -> hover -> click -> open," and I had been faking that with a direct
URL navigation instead of a real click on the visible card.

A second, compounding bug: there was no "return to results" step between jobs.
After opening job #1 via `goto()`, the browser was left sitting on job #1's
detail page. Even if clicking had been wired up, only the FIRST job in a batch
could ever be found and clicked -- job #2 onward would have no card to click
because the browser was no longer on the results listing.

## The fix

1. **`click_job_card()`** (new, `browser/base_portal.py`): locates the job's own
   link on the CURRENT page (by href match, falling back to visible-text match
   scoped to the portal's title selector), scrolls it into view, moves the mouse
   there via the humanizer's curved-path `move_mouse()`, hovers, then performs a
   REAL Playwright `.click()` on the element -- not a raw goto. This dispatches
   trusted DOM click events, so it works for plain `<a href>` links AND
   JS-routed SPA cards. If the element can't be found, it returns False so the
   caller falls back to direct navigation -- a job is never left unopened just
   because its element wasn't locatable.
2. **`open_and_extract()`** (`browser/job_detail.py`) now tries `click_job_card`
   FIRST; only falls back to `navigate()` (goto) when the click path reports it
   couldn't find/use the element. Both paths are logged explicitly: `via REAL
   CLICK (move -> hover -> click)` vs `(fallback) ... direct navigate`.
3. **Return-to-results between jobs** (`collect_incrementally`, Phase 2): after
   each opened job, the browser now calls `page.go_back()` (falling back to a
   forced direct navigate if history back doesn't land on the results page) --
   the literal "open -> read -> extract -> go back -> continue" workflow every
   prompt described. This is what makes clicking work for the SECOND job
   onward, not just the first.

## Files modified

`browser/base_portal.py` (new `click_job_card()`; go-back step in Phase 2),
`browser/job_detail.py` (`open_and_extract` tries click before navigate),
new `tests/test_click_job_card.py`.

## Tests

- 194/194 unit tests pass (5 new); pyflakes/vulture clean; doctor PASS (only
  expected first-run placeholder reminders).
- New unit tests: click finds the element by href / falls back to text match /
  returns False with no match or no selector; `open_and_extract` tries click
  before falling back to navigate.

## Real Playwright proof (the one that matters)

Instrumented a real Chromium page with a genuine DOM `click` event listener
(via `page.add_init_script` + `expose_binding`) and ran the actual production
path -- `NaukriPortal.search()` -> `_build_search_plan()` -> `_browse_plan()` ->
`collect_incrementally()` -- against a local fixture with 4 real Naukri-class
cards (Director, an ambiguous "Senior Manager - Technology Operations", CFO,
Sales).

**Result: 2 real click events captured on the actual DOM**, at the exact
coordinates of each card's link:
```
CLICK card 'Director - IT Infrastructure & Digital Workplace' at (163, 16)
STAGE JOB_OPENED | ... | via REAL CLICK (move -> hover -> click)
... [reads full JD, extracts COMPLETE] ...
Job 1/4 | returned to results page
CLICK card 'Senior Manager - Technology Operations' at (141, 34)
STAGE JOB_OPENED | ... | via REAL CLICK (move -> hover -> click)
... [reads full JD, extracts COMPLETE] ...
Job 2/4 | returned to results page
```
Both opened jobs were **clicked**, not goto'd, and the go-back step correctly
returned to the results page so the SECOND job's card was also found and
clicked -- not just the first. CFO and Sales were skip-opened by the pre-filter,
never clicked, as intended.

## Remaining limitations (honest)

- The click helper matches by href first, then by visible text scoped to the
  portal's title selector. If a live page's title selector or link markup
  differs from the configured defaults, the element still won't be found and
  the code correctly falls back to a direct navigate -- your job still gets
  processed, just without the visible click motion. If you see the fallback log
  line often on the live site, send a `debug/` bundle and I'll tune the selector.
- I cannot reach live Naukri/LinkedIn from the build environment; this proof
  used real Playwright against local fixtures built from the real selector
  classes. Your live run is the final confirmation.

## How to verify on your machine

Run with `debug.visual_mode: true`. Watch the browser: you should see the mouse
visibly move to each card, pause, and click it -- not an instant URL change.
The logs will say `via REAL CLICK` for each one; if you see `(fallback) ...
direct navigate` for most jobs, that tells us the title selector needs tuning
for your live DOM -- send the `debug/` bundle from that run.
