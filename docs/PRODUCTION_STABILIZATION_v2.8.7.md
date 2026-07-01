# CareerPilot v2.8.7 — Production Stabilization

Analysis-first release. No new framework/architecture/AI-providers/diagnostics —
only fixes that make the existing system run reliably end to end. 181 unit tests
pass AND a real end-to-end runtime proof (real collector + detail reader +
pipeline against local fixtures using the real Naukri selectors) passes.

## Root-cause analysis (why it happened, why prior releases failed)

The framework was complete, but the *execution flow* under-delivered at five
points. Earlier releases fixed pieces in isolation (the card-decision gate in
2.8.5, terminal CSV routing in 2.8.6) but three gaps remained, and one earlier
fix had a side effect:

1. **Search not narrowed before opening (#13).** Root cause: `_search_url` had no
   seniority filter and there was NO card-stage open/skip gate. The rule engine's
   title matching only ran AFTER opening. So CFO/finance/sales/hotel cards were
   either opened (wasteful) or stranded. *Why prior releases failed:* they fixed
   what happens to a job AFTER it's found, never reduced WHAT gets opened.
2. **Open/skip logic existed but was unused.** `RuleEngine._title_rule`
   (accepted/rejected titles) is exactly a card filter but was only called inside
   `evaluate()` on the full job.
3. **Stage execution not provable (#15/#19).** Lifecycle logs existed but not the
   uniform `CARD_DETECTED … JOB_FINISHED` markers.
4. **AI execution not provable in one line (#9).**
5. **`browser.open_jobs = OFF` (#2).** Traced end to end: config.yaml →
   `config.py:243` → `BrowserConfig.open_jobs` → `BrowserManager(cfg.browser)` →
   `_browse_plan` reads `session.manager.cfg.open_jobs`. With the repo config it
   resolves **True** at every hop — no code override. The "OFF" came from the
   runtime config file actually loaded, which was invisible. *Fix:* the mandatory
   EFFECTIVE CONFIG banner (added 2.8.6) is the single runtime truth and now also
   prints the config file path.

## Implementation (files modified + why)

- `rules/rule_engine.py` — added `prefilter(job)` (reuses title + blacklist rules
  to decide open/skip from the card; not a fit decision). *Narrows search.*
- `collectors/manager.py`, `browser/base_portal.py`, `browser/linkedin_portal.py`,
  `browser/naukri_portal.py` — thread a `should_open` callback from the pipeline
  (which owns the rule engine) into collection, so the browser gates opening
  WITHOUT importing rules (separation preserved). A card that fails the gate is
  marked `SKIPPED_PREFILTER`, not opened, but still streamed.
- `browser/naukri_portal.py` — `_search_url` appends an `experience=` filter
  (Director-level) to narrow at the URL level.
- `core/pipeline.py` — wired `should_open`; `SKIPPED_PREFILTER` → REJECTED
  (jobs_rejected.csv, "card pre-filter"); uniform stage markers via `_stage()`;
  AI decision+confidence logged; explicit AI-skip reasons.
- `browser/job_detail.py` — `STAGE JOB_OPENED / JD_READING_STARTED /
  JD_READING_COMPLETED` log lines.
- `diagnostics/live_status.py` — added `stage` panel field (#14).

(Retained from 2.8.5/2.8.6 and re-verified: the full-read gate, PARTIAL_DATA →
failed_jobs.csv, the `run_once` diagnostics-reset fix, incremental human reading.)

## Execution flow: before vs after

**Before:** Search → collect every card → store FoundJobs → (decide from card or
strand). 850 jobs in FoundJobs, nothing downstream.

**After:** Search (with experience filter) → card → **pre-filter: worth opening?**
→ if no → REJECTED (not opened); if yes → move mouse/hover → open in tab → wait →
incremental read of full JD → extract all → `read_status` → **gate**: COMPLETE →
Rule → AI (decision+confidence logged) → MATCHED/REJECTED; PARTIAL/UNREAD →
failed_jobs.csv. Every job ends in exactly one of matched/rejected/failed, each
stage logged `CARD_DETECTED … JOB_FINISHED`.

## Test results

- 181/181 unit tests pass; pyflakes + vulture clean; doctor PASS.
- New tests: card pre-filter skips CFO/Sales/Finance, opens Director/Head/Infra;
  `SKIPPED_PREFILTER` → REJECTED terminally (Rule/AI never called); Naukri URL
  carries the experience filter; every found job reaches exactly one terminal.

## Real runtime validation (end-to-end, local fixtures, real selectors)

Drove the real collector + real JobDetailExtractor + real ScanPipeline (real DB +
real CSV; deterministic stub AI) against a Naukri-style results page (real
`div.srp-jobtuple-wrapper` cards) linking to detail pages with full JDs:

| Stat            | Result |
|-----------------|--------|
| Jobs Found      | 3 |
| Jobs Opened     | 1 (CFO + Sales pre-filtered, never opened) |
| Jobs Fully Read | 1 |
| Jobs Matched    | 1 |
| Jobs Rejected   | 2 (card pre-filter) |
| Jobs Applied    | 0 (1 dry-run ready) |
| Jobs Failed     | 0 |

Observed stage log for the matched job:
`CARD_DETECTED → JOB_OPENED → JD_READING_STARTED → JD_READING_COMPLETED →
EXTRACTION_COMPLETED → RULE_ENGINE_COMPLETED(PASS) → AI_COMPLETED(score=82,
confidence=90) → DECISION_COMPLETED(MATCHED) → JOB_FINISHED`. DB statuses and
terminal CSVs matched exactly (1 matched, 2 rejected; FoundJobs=3, none
stranded). `reading_ms=6400` confirms incremental human reading (not instant).

## Remaining live-site limitations (honest)

- I cannot reach live LinkedIn/Naukri from the build environment. The fixtures
  use the REAL selector classes, so the parser + detail reader are proven against
  that DOM shape — but the live sites may use different class names. If they do,
  those jobs become `PARTIAL_DATA` and land in **failed_jobs.csv with a reason**
  (visible, not stranded) and the evidence bundles show the real DOM to fix the
  selectors from evidence.
- The card pre-filter is substring-based (reuses the rule engine), so a title
  containing an accepted term (e.g. "Head Chef" contains "head") will be opened
  and then rejected on the full JD — coarse but safe.
- Live mouse/scroll/reading realism and a long multi-hour run remain yours to
  observe.

## Production readiness assessment

- **Pipeline integrity, terminal routing, gate, pre-filter, stage logging, AI
  proof, DB/CSV consistency:** verified by unit tests AND end-to-end runtime
  against real selectors — production-ready.
- **Live LinkedIn/Naukri selector accuracy and long-run stability:** NOT yet
  verified from here — requires your dry-run. Until confirmed, treat live
  extraction as Tested-pending-live, not Production Ready.

Run: set `debug.visual_mode: true`, `apply.mode: dry_run`; confirm the EFFECTIVE
CONFIG banner shows `open_jobs = True` and the right config file; then verify
every FoundJobs row appears in exactly one of jobs_matched / jobs_rejected /
failed_jobs. Send the `debug/` bundle for any failed_jobs rows to fix live
selectors.
