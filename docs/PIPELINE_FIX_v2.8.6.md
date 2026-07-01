# Execution Pipeline Fix — v2.8.6

No new framework, diagnostics, AI providers, or architecture. This release fixes
the execution pipeline so every discovered job runs the full workflow and ends in
exactly one terminal outcome. 177 tests pass; doctor PASS.

## 1. Root cause analysis: why nothing got past FoundJobs

Two distinct bugs combined to strand ~850 jobs in FoundJobs.csv:

**(a) Partial-Data jobs had no terminal CSV.** The v2.8.5 gate correctly stopped
the Rule/AI engines from deciding on card-only data, marking un-readable jobs
`PARTIAL_DATA`. But the end-of-run CSVs bucket strictly by DB status
(`jobs_rejected.csv`=REJECTED, `jobs_matched.csv`=MATCHED, `jobs_applied.csv`,
`failed_jobs.csv`=failed_jobs table). `PARTIAL_DATA` mapped to NONE of them, so
those jobs vanished from every terminal CSV while still sitting in FoundJobs.csv.
That is the "850 in FoundJobs, everything else empty" you saw.

**(b) `run_once()` reset the diagnostics + status sink to None.** `main` wired
`pipeline.diagnostics` and `pipeline.status_sink` after construction, but the
first lines of `run_once()` set them back to `None` every run — silently
disabling the session report, the live status panel, and per-job metrics during
the actual scan.

**On `browser.open_jobs = OFF`:** traced end-to-end as you asked —
config.yaml → `_build_config` (`open_jobs=bool(browser.get("open_jobs", False))`,
config.py:243) → `BrowserConfig.open_jobs` (session.py:51) →
`BrowserManager(self.cfg.browser)` → `_browse_plan` reads
`self.session.manager.cfg.open_jobs`. With the repo's `config/config.yaml`
(`open_jobs: true`) the value resolves **True** at every step — there is no code
override. The "OFF" therefore came from the runtime config actually loaded (a
different/edited file or stale value), which was invisible. Fix: a mandatory
EFFECTIVE CONFIG banner is now logged at the start of every scan so the real
value is never in doubt:

```
========== EFFECTIVE CONFIG ==========
browser.open_jobs = True
debug.visual_mode = False
apply.mode        = dry_run
portals           = LinkedIn,Naukri
AI Provider       = gemini
AI Model          = gemini-1.5-flash
config file       = config/config.yaml
======================================
```

If your run prints `open_jobs = False`, the banner now also names the config file
in effect — compare it to the file you edited.

## 2. Files modified

- `core/pipeline.py` — removed the `run_once()` reset of diagnostics/status sink;
  PARTIAL_DATA and AI-unavailable jobs now recorded to `failed_jobs` + live
  `FailedJobs.csv` (no stranding); added `counts["failed"]`; wired
  `FailedJobService`.
- `reports/streaming_csv.py` — added `failed()` (live `FailedJobs.csv`).
- `main.py` — `_log_effective_config()` banner before every scan.
- (from v2.8.5, retained) `core/models.py` `read_status`/`missing_fields`;
  `core/enums.py` `PARTIAL_DATA`; `browser/job_detail.py` completeness + retry +
  Partial Data; `browser/humanize.py` `incremental_read`.

## 3. Execution flow: before vs after

**Before:** Search → collect cards → store FoundJobs → next card. (Decisions, if
any, came off the card; un-readable jobs stranded in FoundJobs.)

**After (enforced):** Search → locate card → (human mouse/hover) → open job in a
tab → wait → incremental read of the full JD (scroll/pause/read, scaled to
length) → extract all fields → `read_status` COMPLETE/PARTIAL → **gate**:
- COMPLETE → Rule Engine → (pass) → AI Engine → MATCHED/REJECTED → DB + CSV.
- PARTIAL/UNREAD → retry; still incomplete → `PARTIAL_DATA` → **failed_jobs.csv**
  with reason. → return to results → next card.

The Rule and AI engines are structurally unreachable for a non-COMPLETE job
(unit-tested), so a CFO card can never again be selected without being opened.

## 4. Test results

177/177 unit tests pass; pyflakes/vulture clean; doctor PASS. New/updated tests:
- Rule & AI never run on UNREAD/PARTIAL jobs (the CFO case).
- Every found job reaches exactly one terminal outcome (no stranding).
- PARTIAL_DATA → failed_jobs + FailedJobs.csv with reason.
- `read_status` COMPLETE on a rich JD fixture / PARTIAL on a sparse page
  (real Playwright).
- Incremental reading scales with content; no-op when disabled.

## 5. Real dry-run results & remaining live limitations

I cannot reach live LinkedIn/Naukri from the build environment, so the real
job counts (Found/Opened/Read/Rejected/Matched/Applied/Failed) must come from
your dry-run. What changed for that run:

- With `open_jobs = true` (confirm via the banner) every candidate job is now
  opened and read before any decision.
- If the **live detail selectors don't match** the current Naukri/LinkedIn DOM
  (still unverified from here), those jobs become `PARTIAL_DATA` and now land in
  **failed_jobs.csv with a reason** — visible and accountable, not stranded.
  That is the expected first-run outcome and the signal to fix selectors from the
  evidence bundles (no manual HTML reading needed).
- Human mouse/scroll/reading timing realism on live sites is still yours to
  observe.

Run: `debug.visual_mode: true`, `apply.mode: dry_run`. Then check the banner
(open_jobs), and the four terminal CSVs — every FoundJobs row should now also
appear in exactly one of jobs_rejected / jobs_matched / jobs_applied /
failed_jobs. Send the `debug/` bundle for any failed_jobs rows and the live
selectors get fixed.
