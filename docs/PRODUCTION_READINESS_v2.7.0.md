# CareerPilot v2.7.0 — Production Readiness Report

**Honest bottom line:** the code for this milestone is complete, and everything
buildable here is built and tested (106 automated tests, real-Playwright proofs
against local fixtures). But I cannot certify it production-ready from my build
environment, because the decisive checks in your list require things I have no
access to: the live LinkedIn/Naukri sites, your logged-in session, the live
Gemini/DeepSeek APIs, and a real multi-hour run. Treat this as a RELEASE
CANDIDATE: code-complete, fixture-verified, awaiting your live verification.

Why I can't test live: this environment's network reaches only package
registries and GitHub -- not linkedin.com, naukri.com, or googleapis.com -- and
it has none of your credentials. "Test real browsing, not only unit tests" is the
one instruction I physically cannot satisfy here, and I won't pretend otherwise.

---

## Status of your 19 criteria

Legend: [V] verified here (unit/fixture) - [B] built, needs your live check -
[L] only you can verify (live site / API / long run)

- [B] Browser behaves like a human -- Bezier mouse, idle drift, gradual variable
  scroll with pauses + upward correction, content-scaled reading; on by default,
  deterministic, unit-tested. Whether it actually evades bot-detection is [L].
- [V/B] Opens jobs individually -- job-centric flow built: each job opens in its
  OWN tab, full JD read, extracted, cached, tab closed, results page left intact.
  Proven with real Playwright on a fixture. Gated by browser.open_jobs (default
  off). Live behaviour is [B], pending verified detail selectors.
- [B] Reads / [B] Stores complete JD -- JobDetailExtractor pulls the full
  description + fields and stores them; proven on a fixture. Needs live
  detail-page selectors confirmed via Visual Debug Mode.
- [V] Rule Engine executes correctly -- unit-tested; proven to accept/reject
  parsed jobs end-to-end.
- [B] AI receives complete JD -- when open_jobs is on, the full JD is on the Job
  before the AI Engine sees it. Live-dependent on detail selectors.
- [B] Gemini 404 fixed -- no hardcoded model. resolve_model() queries the live
  model list at startup; if the configured model is gone it auto-selects the
  newest compatible Flash from what the API returns; on API failure it degrades
  gracefully (keeps config, logs). Ranking logic is unit-tested. Actual
  resolution against your key is [L] -- run: python -m careerpilot.main models
- [B] DeepSeek/Kimi works -- DeepSeek provider present; providers try in order
  with retries; AI failure queues the job and continues. Kimi is not a dedicated
  provider yet (it is OpenAI-compatible and can be added via config). Live [L].
- [V] CSV updates live -- streaming per-state CSVs, unit-tested.
- [V] Database updates live -- per-stage commits, unit-tested.
- [V] Visual Debug Mode -- overlays/panel/diagnostics/evidence, fixture-proven;
  panel shows state/search/location/job#/mouse/scroll/cards/reading/missing
  fields/cache. AI-decision/network/retry fields are logged in the pipeline but
  not mirrored into the in-page panel (small noted gap; browser stays decoupled).
- [V] Crash recovery -- already-seen jobs skipped via persistent DB + job cache;
  unit-tested. A real crash-and-resume on a live run is [L].
- [V] Duplicate jobs skipped -- dedupe by URL + content-hash; unit-tested.
- [V/B] Human interaction (CAPTCHA/OTP) -- pause + screenshot + HTML + state +
  Telegram-notify path exists; triggering it needs live selectors [B].
- [L] LinkedIn stable / [L] Naukri stable -- cannot test from here.
- [V] Logs explain every action -- per-job lifecycle logging with sequence
  numbers across discover -> open -> read -> extract -> rule -> AI -> decision
  -> CSV -> DB -> next.
- [V] No silent failures -- per-job/per-portal isolation logs every path.
- [L] Long-running scan tested -- requires a live multi-hour run.

---

## What changed in this milestone

- Gemini: dynamic model discovery + startup validation + auto-fallback to newest
  Flash + graceful degradation (never stops the pipeline; queues + continues).
- Job-centric flow: open-in-separate-tab -> read full JD -> extract all fields ->
  cache -> close, wired through the streaming pipeline (detail runs before
  Rule/AI), gated by browser.open_jobs.
- New browser states used (OPENING_JOB, READING_JOB, SCROLLING_JOB, EXTRACTING).
- Separation preserved: browser/ imports no Rule/AI; the detail extractor is
  browser-only; the pipeline injects the callbacks.

## The honest gap (unchanged blocker)

Every [B]/[L] above funnels to one thing: the live DOM selectors (card + detail)
and the live API/session, which I cannot reach. Everything is built to consume
them the moment you verify them.

## What only you can do to finish certification

1. python -m careerpilot.main models  -> set ai.gemini_model to a listed model.
2. debug.visual_mode: true, run a Chennai/Director Naukri search; confirm card
   overlays highlight real cards. Adjust portals.naukri selectors if not.
3. Open one job; confirm portals.naukri.detail selectors capture the JD. Then
   set browser.open_jobs: true.
4. python -m careerpilot.main validate  -> confirm each stage shows non-zero.
5. Run for an hour with apply.mode: dry_run; watch the live CSVs and the logs.

Only after 1-5 pass on your machine is this truly v2.7.0 production-ready.
