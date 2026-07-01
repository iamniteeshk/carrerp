# Human Browser Automation Engine — v2.8.5

No architectural rewrite: the existing Browser, Portal, Rule, AI, Apply,
Database, CSV, Dashboard and Diagnostics modules are extended, not replaced.
176 tests pass. This release fixes the core bug you observed and makes the
browser read jobs like a person before any decision is made.

## The bug you saw, and the fix

You observed: Naukri cards were identified, but an unrelated **CFO job was
selected from the card** — it was never opened, and the decision was made from
card data alone.

Root cause: detail-reading was optional and decoupled from the decision. The
Rule Engine ran on whatever the job had, even card-only data.

Fix — a HARD GATE in the pipeline: the Rule and AI engines now decide **only on
a job whose full JD was read** (`read_status == COMPLETE`). A job that was never
opened (`UNREAD`) or only partially read (`PARTIAL`) is marked **Partial Data**
and is never selected or rejected-for-fit. An unread CFO card therefore can no
longer be selected — it is opened and judged on its real JD, or held as Partial
Data. There is a test that asserts the Rule and AI engines are never called on an
unread job.

## What was implemented (mapped to your spec)

- **Full job reading is mandatory before decisions.** `read_status` on the Job
  (UNREAD/COMPLETE/PARTIAL); `assess_completeness()` requires a substantive JD.
  The detail reader retries on an incomplete read, then marks Partial Data with
  an evidence bundle — never silently accepts or rejects.
- **Human reading workflow.** `incremental_read()` reads the top section, pauses,
  scrolls a slice, pauses, reads, and continues — the number of passes scales
  with JD length (short JD = 1–2 passes, long JD = up to 8). Deterministic under
  the seed; tested.
- **Human mouse behaviour** (already present, retained): curved Bézier movement,
  variable speed, small overshoot + correction, hover-before-click, idle drift,
  scroll-wheel stepping (no page jumps). Mouse/scroll feed the recorder.
- **Incremental extraction + cache** (retained/extended): fields filled while
  reading, combined into one Job, cached (no reopen unless changed/expired).
- **Partial Data status** end-to-end: new `JobStatus.PARTIAL_DATA`, counted
  separately, surfaced in logs and the session report.
- **Visual Debug panel** gains Reading Section, Time Reading, Extracted Fields,
  Missing Fields (additive to the live status sink).
- **Per-job diagnostics**: screenshot, HTML, parsed JSON, reading time, mouse/
  scroll events and the reading timeline are saved (extends the existing bundle).
- **Live CSV + DB** unchanged: every processed job still writes immediately;
  Partial Data jobs are recorded too (never silently dropped).
- **Reliability over speed**: slower, complete reads are preferred; `open_jobs`
  defaults ON and the pipeline warns loudly if it is disabled (because then no
  fit decision can be made).

## Verified locally vs needs live validation

**Verified here (fixtures + real Playwright + 176 unit tests):**
- The gate: Rule/AI never decide on UNREAD/PARTIAL jobs; CFO-from-card is
  impossible (test).
- `read_status` COMPLETE on a rich JD fixture, PARTIAL on a sparse page
  (real Playwright, separate tab, cache intact).
- Incremental reading scales with content; no-op when disabled.
- Detail retry + Partial Data marking + evidence bundle on incomplete reads.
- Full suite green; doctor PASS; no regression to AI providers, diagnostics,
  CSV, DB, dashboard.

**Still requires YOUR live run (I cannot reach live LinkedIn/Naukri):**
- That the live Naukri/LinkedIn **detail selectors** actually fill the JD on the
  real pages (if they don't, every job becomes Partial Data — which is the
  correct, safe failure, and the evidence bundles will show the real DOM so the
  selectors can be fixed).
- Real human-likeness of mouse/scroll timing on the live sites.
- A full long-running scan without crashing against live portals.

Run with `debug.visual_mode: true` and `apply.mode: dry_run`. If jobs come back
Partial Data, that is the gate working: send the `debug/` bundle and the real JD
selectors get fixed from evidence — not guesswork. This is the honest state: the
decision bug is fixed and proven; the live selector accuracy is the next thing
your evidence will close.
