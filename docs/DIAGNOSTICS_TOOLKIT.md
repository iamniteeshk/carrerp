# Diagnostics & Developer Toolkit — v2.8.0

A new first-class component (`careerpilot/diagnostics/`) that makes the Browser
Engine fully observable, so failures no longer need manual reproduction. It only
observes/records — it never drives application logic — and is gated by
`debug.visual_mode` (off = unchanged behaviour). Every feature below is tested
(116 automated tests; the job-detail recorder + graceful-failure path also proven
against real Playwright fixtures).

## What was built (mapped to your points)

1. **Automatic DOM Recorder** — every exported page folder contains full HTML,
   full-page AND viewport screenshots, parsed jobs, raw page text, browser state,
   URL, search/location/portal, the selectors used, selector match counts, scroll
   position, timestamp and JSON metadata. Written automatically; no manual saving.
2. **Job Detail Recorder** — each opened job saves its own bundle under
   `debug/session/<portal>/jobs/job_NNN/` (HTML, screenshots, parsed job,
   raw text, selectors, browser state) so the parser can be improved later
   without revisiting the site.
3. **Selector Inspector** — every selector reports matched / visible / hidden +
   first-match text; a selector matching nothing is logged as an explicit
   FAILURE, never silently skipped.
4. **Browser Replay** — an `InteractionRecorder` logs navigation, mouse moves,
   clicks, scrolls, keys and waits (plus console + network) to `replay.json`;
   `diagnostics.replay` re-issues them on a page, pacing by the recorded gaps.
5. **Live Browser Inspector** — a shared `LiveStatus` sink that both the Browser
   Engine and the pipeline write to (state, search, location, job #, title,
   mouse, scroll, cards, rule decision, AI status, resume, CSV/DB status, retry,
   portal, URL, wait reason). The Visual Debug panel renders it live.
6. **DOM Export** — one command:
   `python -m careerpilot.main export <url> [linkedin|naukri]`
   dumps page.html, page.png, viewport.png, parsed.json, selectors.json,
   console.log, network.json, browser_state.json, metadata.json, timeline.json.
7. **Better Failure Evidence** — `FailureEvidence.capture(kind, …)` writes a
   full bundle for selector failures, timeouts, CAPTCHA/OTP, redirects, crashes,
   network and AI errors (screenshot, HTML, state, URL, job, search, location,
   timeline, console, network).
8. **Do NOT disable features** — job-detail extraction now stays ON
   (`browser.open_jobs: true`, experimental): it retries on failure, captures an
   evidence bundle, logs the exact reason, and continues with card data. It is
   never silently switched off. (Proven: a job whose selectors don't match
   retried, saved a `job_detail_empty` bundle, and the scan continued.)
9. **Reduce manual work** — with debug mode on, HTML/DevTools/DOM/screenshots/
   selector identification/page export are all collected automatically.
10. **Human behaviour** — unchanged and intact (Bezier mouse, gradual scroll,
    reading pauses); mouse/scroll are now also fed to the recorder.
11. **Architecture** — Diagnostics is its own package; it imports no Rule/AI;
    the browser/pipeline write to the shared status sink without importing each
    other. No working module was rewritten.

## Honest scope note

Everything here is verified against local fixtures and real Playwright. What it
CANNOT do from my environment is run against live LinkedIn/Naukri — but that is
exactly the point of this milestone: when YOU run it, the toolkit captures the
real DOM, selectors, screenshots and evidence automatically, so improving the
live selectors becomes a desk job (read the saved bundle) instead of a live
repro. Turn on `debug.visual_mode`, run a search, and send me
`debug/session/naukri/jobs/job_001/` (or any failure bundle) — that's all I need
to write verified selectors.
