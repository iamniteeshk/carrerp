# Live Processing & Streaming Pipeline — v2.6.0

The pipeline is now event-driven: each job runs the full workflow the instant it
is discovered, instead of collecting everything first and processing at the end.
No module was rewritten — the Browser/State/Rule/AI/Human/Debug engines are
unchanged; only the *flow* between them became streaming.

## What changed

**Streaming collection.** `collect_incrementally` gained an `on_job` callback that
fires the moment each new card is parsed — before scrolling further. The pipeline
injects its per-job processor as that callback, so the Browser Engine stays fully
decoupled (it imports no Rule/AI code; it just calls a function it was handed).
`CollectorManager.collect_streaming(on_job)` drives this across portals; one
portal failing never stops the others. Proven with real Playwright: 6 jobs on an
infinite-scroll page were each processed as they appeared, not in one batch.

**Per-job pipeline.** `_process_job` runs ONE job end-to-end immediately:
discover → INSERT (DB commit) → FoundJobs.csv → Rule Engine → (reject → DB +
RejectedJobs.csv) or (pass → SelectedJobs.csv → AI → DB + MatchedJobs.csv →
apply/dry-run → AppliedJobs.csv). Each stage commits/flushes as it happens.

**Live CSVs.** New `StreamingCSVReporter` appends a row to the relevant per-state
file the instant a job changes state: FoundJobs.csv, RejectedJobs.csv,
SelectedJobs.csv, MatchedJobs.csv, AppliedJobs.csv. Tail them while a scan runs;
on a crash, everything processed so far is already on disk. (The end-of-scan
summary CSVs are still generated too.)

**Crash recovery.** Before processing, a job already in the DB (this run or a
previous one) is skipped and logged. Because writes happen per job, a restart
continues where it left off — crash after job 143, next run resumes at 144.

**Event-driven logging.** Every job logs its lifecycle with a sequence number:
`Job #27 DISCOVERED → SAVED → PASSED Rule Engine → AI SCORE 94 / profile=Infrastructure
→ AppliedJobs.csv → COMPLETE`. Nothing is processed silently.

## Human scrolling (your bot-detection concern)

Human browsing is now ON by default (`human.enabled: true`): gradual variable
scroll steps with pauses and occasional upward correction, reading time scaled to
content, curved mouse movement. Critically, even with human mode OFF the fallback
no longer does a single full-height `scrollBy` jump — it does several medium steps
with short pauses (`_gradual_scroll`). The old one-shot jump-to-footer (the
obvious bot tell) is gone from both paths.

## Honest status

- Streaming architecture, live CSVs, per-stage DB commits, crash-recovery skip,
  event logging, gradual scrolling: built and tested (98 tests), streaming proven
  against a real infinite-scroll page.
- Still needs live DOM (unchanged): verified card/detail selectors, and the
  open-each-job *detail page* read (the callback is ready to host it). Streaming
  currently runs at the card level; when detail selectors are verified, the same
  callback opens each job, extracts the full JD, caches it, then continues.
- Gemini model name: set it via `python -m careerpilot.main models`.
