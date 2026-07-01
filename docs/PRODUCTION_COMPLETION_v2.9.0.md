# CareerPilot v2.9.0 — Production Completion (Quality over Quantity)

Goal of this release: **find the right jobs, behaving like a human**, not build
features. No new framework/architecture/analyzers were added — only production
fixes. 185 unit tests pass, lint clean, doctor PASS, and a real end-to-end
runtime proof (real collector + real detail reader + real pipeline against
Naukri-shaped fixtures) passes.

## The headline root cause — "jobs are never opened"

You watched the browser change search URLs but never open job pages. I found the
exact cause, and it was a bug I introduced in 2.8.7:

The card pre-filter (`should_open`) called `RuleEngine._title_rule`, which is
**fail-closed**: `if accepted_titles and not has_accepted_title(title): reject`.
Live Naukri card titles rarely contain your configured title phrases verbatim, so
**every card failed the gate and nothing was ever opened** — exactly the symptom.

**Fix (root, not symptom):** `prefilter` is now a **fail-open denylist**. A card
is opened UNLESS its title clearly belongs to an unrelated domain (CFO, finance,
sales, plant, medical, hotel, legal, ... — built-in `OFF_DOMAIN_TERMS`, plus your
`rejected_titles`). Anything not clearly off-domain is opened and judged on the
full JD. A pre-filter can never again skip everything. Proven: ambiguous titles
like "Senior Manager - Technology Operations" are now opened; CFO/Sales are
skipped before opening.

## Every bug fixed (with root cause)

1. **Never opened (#1, #10).** Root: fail-closed card pre-filter. Fix: fail-open
   denylist `prefilter` + built-in off-domain list. *Files:* `rules/rule_engine.py`.
2. **Cached jobs wrongly marked Partial Data.** Root: on a cache hit,
   `open_and_extract` returned WITHOUT setting `read_status`, so it defaulted to
   `UNREAD` and the gate failed the job every re-encounter. Fix: cache-hit path
   now runs `assess_completeness` and sets `read_status`/`missing_fields`.
   *Files:* `browser/job_detail.py`. (Found via a warm-cache e2e run.)
3. **Opening was invisible (#1, #18).** Root: jobs opened in a background tab you
   weren't watching. Fix: `page.bring_to_front()` on the job tab + a loud
   `STAGE OPENING_JOB` log. *Files:* `browser/job_detail.py`.
4. **Search went broad too early (#6, #7).** Root: keyword-major plan searched
   each keyword across all cities before finishing Chennai. Fix: **location-major**
   plan — the first preferred location (Chennai) is searched across every keyword
   before the next city; nationwide is strictly last. *Files:* `browser/base_portal.py`.
5. **Search vs. match conflated (#6, #8).** Root: `accepted_titles` was used both
   as the search list AND the relevance allowlist — a focused search and a broad
   "does this fit" check can't be one list. Fix: new **`search_keywords`** config
   (focused, point-6 list) for searching; `accepted_titles` stays the broad
   match allowlist. Backward compatible (falls back to `accepted_titles`).
   *Files:* `core/config.py`, `main.py`, `config.example.yaml`, `config/config.yaml`.
6. **Robotic browsing (#4).** Root: reading/scrolling too fast. Fix: realistic
   timings — 220 wpm, 0.9–12s reading, 120–380px scroll notches, 0.6–1.8s pauses.
   *Files:* `browser/humanize.py`.
7. **`open_jobs` invisible (#10).** Traced end to end (config.yaml → config.py:243
   → BrowserConfig → BrowserManager → `_browse_plan`); resolves True with no code
   override. Fix: EFFECTIVE CONFIG banner now prints a `job-open path =
   READY/DISABLED/BROKEN` line + config file path + a loud warning when not READY.
   *Files:* `main.py`.
8. **Stranded jobs / provable stages / AI proof (#11, #13, #15).** (From 2.8.5–
   2.8.7, retained & re-verified.) Every found job ends in exactly one of
   matched/rejected/failed; uniform `CARD_DETECTED … JOB_FINISHED` markers; AI
   logs provider/model/score/confidence; PARTIAL/AI-unavailable → failed_jobs.csv.

## New: markdown run-log (explicit request — "add all logging to a md file")

At the end of every run the pipeline writes `reports/run_log_<timestamp>.md` with
a summary table (found/matched/rejected/failed/applied, terminal coverage) and the
full per-job stage trace. *Files:* `core/pipeline.py` (`_write_run_log_md`).

## Files modified

`rules/rule_engine.py`, `browser/job_detail.py`, `browser/base_portal.py`,
`browser/humanize.py`, `core/pipeline.py`, `core/config.py`, `main.py`,
`config.example.yaml`, `config/config.yaml`, and tests
(`tests/test_prefilter.py`, `tests/test_read_gate.py`, `tests/test_navigation.py`).

## Tests executed

- 185/185 unit tests pass; `pyflakes` + `vulture` clean; `doctor` PASS.
- Key new tests: prefilter is fail-open for ambiguous titles and skips clear
  off-domain; cache-hit sets `read_status` COMPLETE (and PARTIAL when JD absent);
  run-log markdown is written; every found job reaches exactly one terminal.

## End-to-end runtime proof (real code, Naukri-shaped fixtures)

Drove the real collector + real `JobDetailExtractor` + real `ScanPipeline`
(real DB + real CSV; deterministic stub AI) against a results page using the
real `div.srp-jobtuple-wrapper` card class, linking to detail pages with the real
`section.styles_job-desc-container__txpYf` JD container. Four cards: a Director
role, an ambiguous "Senior Manager - Technology Operations", a CFO, a Sales role.

| Stat            | Result |
|-----------------|--------|
| Jobs Found      | 4 |
| Jobs Opened     | 2 (Director + ambiguous; CFO & Sales skipped before opening) |
| Jobs Fully Read | 2 |
| Jobs Matched    | 2 |
| Jobs Rejected   | 2 (CFO, Sales — card pre-filter, never opened) |
| Jobs Applied    | 2 (dry-run ready) |
| Jobs Failed     | 0 |
| Stranded        | 0 (DB == CSV: 2 matched, 2 rejected) |

Observed stage trace for an opened job:
`CARD_DETECTED → STAGE OPENING_JOB → JD_READING_STARTED → JD_READING_COMPLETED →
EXTRACTION_COMPLETED → RULE_ENGINE_COMPLETED(PASS) → AI_COMPLETED(score, confidence)
→ DECISION_COMPLETED(MATCHED) → JOB_FINISHED`. A **warm-cache** re-run produced
identical results (matched=2, partial=0, failed=0), proving the cache-hit fix.

## Known limitations (honest)

- I cannot reach live LinkedIn/Naukri from the build environment. Fixtures use the
  REAL selector classes, so the parser + reader are proven against that DOM shape,
  but the live sites may use different class names. If they do, those jobs become
  PARTIAL_DATA and land in **failed_jobs.csv with a reason** (visible, not
  stranded); the evidence bundles capture the real DOM to fix selectors from
  evidence — no manual HTML reading needed.
- Naukri URL filters added: experience (15+) and location (slug). Other portal
  filters (work-mode/posted-date/department) are not yet wired into the URL.
- The card pre-filter and the rule engine's title match are substring-based, so a
  title containing an accepted term (e.g. "Head Chef" contains "head") is opened
  and rejected later on the full JD — coarse but safe.
- Multi-hour unattended stability has not been run here.

## Production readiness

- **Verified here (unit + real-selector runtime): production-ready** — jobs are
  opened, full JD read, Rule→AI on complete data, fail-open pre-filter, Chennai-
  first location-major search, terminal routing (no stranding), stage logging, AI
  proof, cache correctness, markdown run-log.
- **Needs your live dry-run:** live LinkedIn/Naukri selector accuracy and a long
  unattended run. Until confirmed, treat live extraction as Tested-pending-live.

### How to run and confirm
1. Ensure `config/config.yaml` has your focused `search_keywords` and broad
   `accepted_titles` (templates updated in `config.example.yaml`).
2. Set `browser.open_jobs: true`, `debug.visual_mode: true`, `apply.mode: dry_run`.
3. Run a scan. Confirm the EFFECTIVE CONFIG banner shows `job-open path = READY`
   and the right config file; watch jobs open one at a time and read.
4. Check `reports/run_log_<timestamp>.md` and that every FoundJobs row appears in
   exactly one of jobs_matched / jobs_rejected / failed_jobs.
5. For any failed_jobs row, send the `debug/` bundle and the live selectors get
   fixed from evidence.
