# CareerPilot v2.9.1 — Production Root Cause Fix & Stabilization

A debugging/stabilization release. No new framework. I traced the full pipeline
against your live observations and fixed the real root causes. 189 unit tests
pass, lint clean, doctor PASS, end-to-end runtime proof passes, and the ZIP is
validated clean before release.

## Investigation — what I traced, stage by stage

- **"never opened (enable browser.open_jobs)" (Issue 2):** this message fires ONLY
  when `read_status == "UNREAD"`. If a job were opened and extraction failed,
  status would be PARTIAL, not UNREAD. So UNREAD proves the open was never
  effectively executed. I traced config → BrowserConfig → portal → `_browse_plan`:
  `open_jobs` resolves True and both portals correctly store `detail_extractor`,
  so `detail_fn` IS built. The failure was at execution: the old `detail_fn`
  opened each job in a **new tab** (`session.new_tab()`) and **swallowed any
  exception**, leaving `read_status` at its UNREAD default. If `new_tab()` fails
  (or the job page throws before extraction), every job silently ends UNREAD →
  Partial Data → failed. That is the 720-failed / 0-matched pattern (Issue 4).
- **Debug panel middle pipeline blank, stage=JOB_FINISHED (Issue 3):** consistent
  with the above — jobs reached the read-gate UNREAD and went straight to the
  failed terminal without opening/reading/AI.
- **630+ "already processed" on a fresh run (Issue 5):** traced to `exists()`
  dedup. The location-major plan issues many keyword×location searches that return
  the SAME jobs; the first encounter is inserted, later encounters are legitimate
  duplicates. It is within-run dedup, NOT stale data — but the message was
  alarming and the ZIP cleanliness wasn't enforced. Both fixed below.

## Root-cause fixes

1. **Jobs are now opened in the SAME visible tab (Issues 1, 2, 3).** Rewrote the
   collector to **two phases**: (1) scroll + collect every card first, then
   (2) open each collected job in the main tab, read the full JD, extract, and
   process. This matches the human workflow (open → read → next), is visible in
   the window you watch, and eliminates the `new_tab()` failure mode entirely.
   *Files:* `browser/base_portal.py`.
2. **Open failures are never silent (Issues 2, 14).** If opening throws, the job
   is set to `PARTIAL` with a precise `missing_fields` reason (e.g. "open failed:
   navigation timeout") instead of a swallowed UNREAD. A cache hit now also sets
   `read_status` (fixed in 2.9.0). *Files:* `browser/base_portal.py`,
   `browser/job_detail.py`.
3. **Job-open path is loudly reported (Issues 2, 7).** If `open_jobs` is off or no
   reader is wired, each portal logs a clear warning at search start, and the
   startup banner shows `job-open path = READY/DISABLED/BROKEN`.
4. **Full runtime configuration banner (Issue 7).** At startup CareerPilot prints
   package version, absolute config path, database/reports/screenshots/logs/
   browser-profile paths, `open_jobs`, `visual_mode`, apply mode, portals, search
   titles, location order, and the AI provider/model. *Files:* `main.py`,
   `core/config.py` (added `source_path`).
5. **Fresh ZIP starts clean and runs directly (Issues 5, 6).** The ZIP ships NO
   database/CSV/logs/cache/profiles/pyc. A first-run bootstrap creates
   `config/config.yaml` from `config.example.yaml` automatically so the app runs
   without manual setup. *Files:* `main.py` (`_bootstrap_config`).
6. **Packaging validator (Issues 6, 18).** `scripts/validate_clean.py` fails
   packaging if any runtime artifact (db, csv, logs, debug, screenshots, cache,
   browser profiles, Playwright state, `__pycache__`, `.pyc`, `.DS_Store`,
   `Thumbs.db`) is present. It is run against the EXTRACTED release ZIP so we
   validate exactly what ships.
7. **Dedup message clarified (Issue 5).** "Skipped (already processed)" →
   "SKIPPED (duplicate — same job already seen this run or in the database from a
   prior run)".
8. **Retained & re-verified (2.8.5–2.9.0):** fail-open card pre-filter (opens
   ambiguous, skips clear off-domain — the fix for the earlier never-opened bug),
   location-major Chennai-first search, Naukri experience filter, focused
   `search_keywords` vs broad `accepted_titles`, realistic human timings, uniform
   stage logging, terminal routing (no stranding), markdown run-log.

## Before vs after execution flow

**Before:** scroll → parse card → (open in hidden new tab; swallow errors) →
process. New-tab failure → every job UNREAD → Partial Data → failed.

**After:** scroll → collect ALL cards → for each: PRE_FILTER (open/skip) → open in
the SAME visible tab → wait → read full JD (incremental, human-paced) → extract →
Rule Engine → AI → MATCHED/REJECTED → CSV + DB → JOB_FINISHED. Open failure →
PARTIAL with a precise reason → failed_jobs.csv.

## Files modified

`browser/base_portal.py`, `browser/job_detail.py`, `core/config.py`, `main.py`,
`core/pipeline.py`, `careerpilot/__init__.py`, new `scripts/validate_clean.py`,
and tests (`tests/test_two_phase_open.py`, plus updates).

## Tests executed

- 189/189 unit tests pass; pyflakes + vulture clean; doctor PASS.
- New: two-phase collect opens only pre-filtered jobs and streams all; open
  failure → PARTIAL with reason (never UNREAD); packaging validator flags runtime
  artifacts and passes when clean.

## End-to-end runtime proof (real code, Naukri-shaped fixtures, SAME-TAB flow)

Real collector + real detail reader + real pipeline against a results page using
the real `div.srp-jobtuple-wrapper` card class and real
`section.styles_job-desc-container__txpYf` JD container. Four cards: Director,
ambiguous "Senior Manager - Technology Operations", CFO, Sales.

| Stat            | Result |
|-----------------|--------|
| Jobs Found      | 4 |
| Jobs Opened     | 2 (in the same tab; CFO & Sales skipped before opening) |
| Jobs Fully Read | 2 |
| Jobs Matched    | 2 |
| Jobs Rejected   | 2 (CFO, Sales — pre-filter, never opened) |
| Jobs Failed     | 0 |
| Stranded        | 0 (DB == CSV) |

A warm-cache re-run produced identical results (0 partial, 0 failed), confirming
the cache-hit fix.

## Remaining limitations (honest)

- I cannot reach live LinkedIn/Naukri from the build environment. Fixtures use the
  REAL selector classes, so the parser + reader are proven against that DOM shape,
  but live pages may differ. If they do, those jobs become PARTIAL and land in
  failed_jobs.csv **with a precise reason** (not stranded); send a `debug/` bundle
  and the live selectors get fixed from evidence.
- Human mouse/scroll realism and a multi-hour unattended run remain yours to
  observe. Timings are now realistic (220 wpm, 0.6–1.8s scroll pauses).

## Production readiness

- **Verified here (unit + real-selector runtime): production-ready** — same-tab
  visible opening, full-JD read before any decision, no silent UNREAD, terminal
  routing, clean-ZIP packaging validation, first-run bootstrap, full config
  visibility.
- **Needs your live dry-run:** live selector accuracy + long unattended run.

### How to run
1. Unzip anywhere. `pip install -r requirements.txt` and
   `playwright install chromium`.
2. `python -m careerpilot.main run` — on first run it creates
   `config/config.yaml` from the example; review `search_keywords`,
   `accepted_titles`, `preferred_locations`, and your AI key.
3. Set `browser.open_jobs: true`, `debug.visual_mode: true`, `apply.mode: dry_run`.
4. Watch the EFFECTIVE CONFIG banner (`job-open path = READY`), watch each job
   open in the tab, then check `reports/run_log_<timestamp>.md` and that every
   FoundJobs row is in exactly one of jobs_matched / jobs_rejected / failed_jobs.
