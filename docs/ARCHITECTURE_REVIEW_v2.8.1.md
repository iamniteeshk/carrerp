# CareerPilot Architecture Review (v2.8.1)

Per point #10: findings + recommendations only. No code was changed as part of
this review. Grounded in the actual tree: 67 modules, ~7,460 LOC, 129 tests.

## What is healthy

- **Engine separation holds.** Verified: `browser/` imports no `ai/` or `rules/`
  code; the pipeline injects callbacks; diagnostics imports neither. This is the
  most important invariant and it is intact.
- **Single Playwright instance / single scan thread** removes the original
  Naukri async crash and whole classes of race conditions.
- **Streaming + per-stage commits + job cache** give real crash recovery.
- **Diagnostics is now a clean plugin layer** (analyzers register without core
  changes); pure-data analyzers are trivially testable.

## Weak points & technical debt (ranked)

1. **`base_portal.py` is 638 lines and does too much** -- navigation, readiness,
   state logging, incremental collection, generic card parsing, the browse
   orchestration, AND the card helpers all live in one file. *Recommendation:*
   split into `navigation.py` (navigate/wait_for_ready/state), `collector.py`
   (collect_incrementally + browse_plan), and `parsing.py` (card helpers +
   `_parse_result_cards`), keeping `BasePortal` as the thin contract. Mechanical,
   low-risk, high readability payoff. Do it before the file grows further.
2. **Duplicated `_safe` helper in 5 modules** (visual_debug, humanize, exporter,
   evidence/recorder, replay). *Recommendation:* one `core/safe.py` `safe(fn,
   default=None)` and import it. Small, removes drift risk.
3. **Card-text extraction exists in two shapes** -- `_card_text/_card_attr` in
   base_portal and `_text/_attr` in the exporter/job_detail. *Recommendation:*
   consolidate into a `browser/dom.py` utility used by both.
4. **`main.py` `_build_portals` is a long wiring method** (debugger, humanizer,
   cache, diagnostics, extractor, status links). *Recommendation:* extract a
   small `BrowserStack` builder so wiring is declarative and testable; reduces
   the chance of an ordering bug (we hit one: humanizer.recorder set after
   diagnostics).
5. **Unverified live selectors remain the central risk** (not a code flaw, a
   data gap). *Recommendation:* the new Selector/DOM-Diff analyzers + evidence
   bundles are the mitigation; keep selectors 100% config-driven (already true).

## Potential race conditions

- Low risk today: one scan thread, one Playwright instance. *Watch item:* the
  job-detail flow opens a second tab in the same context -- safe while
  single-threaded, but do NOT parallelize portals/jobs without moving to
  separate contexts and an async or process model. Document this constraint.
- `LiveStatus` uses a lock (fine). `RunMetrics` is single-thread by assumption;
  if a future async model lands, make its increments atomic.

## Performance / memory

- `raw_html`/`full_html` captured per job can be large; the cache stores them.
  *Recommendation:* cap stored HTML length (e.g. 200KB) or gzip the cache files;
  add a cache-eviction/age policy for long-running deployments.
- `collect_incrementally` keeps all `seen` jobs in memory per search; fine at
  realistic volumes, but for very large searches consider flushing to the
  pipeline and dropping references (the streaming `on_job` already enables this).
- Full-page screenshots every page in debug mode are I/O heavy; gate the
  full-page (vs viewport) shot behind a sub-flag for long runs.

## Maintainability / scaling concerns

- **Provider pluggability** is partial: Gemini + DeepSeek are concrete; Kimi and
  others would currently need a new class. *Recommendation:* a small
  `AIProvider` registry + an OpenAI-compatible generic provider (base_url +
  model + key) would make Kimi/DeepSeek/others pure config.
- **Selectors live in code defaults + config**; as portals multiply this should
  move to a per-portal selector pack (one file per portal) loaded by name.
- **Test fakes are duplicated** across test files (FakePage variants).
  *Recommendation:* a shared `tests/_fakes.py` to reduce drift.
- **No typed config schema validation** beyond `_validate_semantics`; a schema
  (pydantic/dataclass validation) would catch malformed YAML earlier.

## Suggested sequence (when you choose to act)

1. `core/safe.py` + `browser/dom.py` (dedupe, zero behaviour change).
2. Split `base_portal.py` (navigation/collector/parsing).
3. AI provider registry + generic OpenAI-compatible provider (unlocks Kimi).
4. Per-portal selector packs.
5. Cache size/eviction policy for unattended long runs.

None of these are urgent; the system is coherent and tested. They are the
investments that keep it maintainable as portals and providers grow.
