# Human Browsing Engine — v2.5.0

This round addressed the two explicitly-broken items and extended the engine
toward human-like browsing, following §17 (extend, don't rewrite). The separation
holds: browser/ imports no AI, ai/ never touches a page, rules/ imports neither.

## Fixed (concrete bugs)

**§14 — job title showing "?".** Root cause was a field-name mismatch, not the
parser: the debug logging/serialization read `title`/`easy_apply`, but the Job
dataclass uses `job_title`/`is_easy_apply`. The card parser was already extracting
the title correctly; the display was wrong. Fixed in visual_debug.py. The card
parser returns a complete Job (title, company, location, experience, salary,
easy-apply, url) via config-driven selectors.

**§15 — Gemini HTTP 404.** I did NOT guess a model name (names change across API
versions and I can't verify live). Instead the fix is mechanical and honest:
- `GeminiProvider.list_models()` queries the live `v1beta/models` endpoint for the
  models your key actually supports (the authoritative source).
- A 404 now returns a clear error listing the available models and telling you to
  set `ai.gemini_model`, instead of an opaque "not found".
- New command: `python -m careerpilot.main models` prints the valid model names
  for your key and flags if your configured model isn't among them.

Set `ai.gemini_model` in config.yaml to a name that command returns (e.g. a
current Gemini 2.x Flash variant) and the AI Engine works again. I can't confirm
the exact string from here — that's what `models` is for.

## Extended

**§2 — curved human mouse.** Movement now follows a quadratic Bézier curve with a
randomized control point (not a straight line), a slight overshoot then settle,
hover-then-click with a pre-click pause, and occasional idle drift to blank areas.
Deterministic under a seed (tested).

**§6/§12 — Job Memory Cache.** New `core/job_cache.py`: persists opened jobs to
disk keyed by normalized URL, with a content hash for change detection. `needs_open`
returns False on a cache hit (unchanged) and True only when missing or changed, so
a job seen again tomorrow isn't reopened. Hit/miss/changed stats tracked. Wired
into startup; the open-job *detail extraction* that fills the cache is the live-DOM
step below.

**§13 — richer debug panel.** The floating panel now also shows the reading timer,
mouse position, missing-fields summary, and cache stats, alongside the existing
state/search/scroll/counters.

**§3/§8 — human scrolling & reading** (from 2.4.0, intact): gradual variable-size
scroll steps with pauses and occasional upward correction; reading pauses scale
with content size.

## Honestly NOT done this round (need live DOM/API — won't fake)

- **§5/§7 — open every relevant job, read the full JD page, extract everything,
  cache, then AI.** The cache and the read/scroll behaviour exist; the job-detail
  *page* extraction needs detail-page selectors verified against the live DOM. The
  card→rule→open ordering change waits on that.
- **§9/§10 — UI-driven navigation via Naukri's search box and filters** instead of
  URLs. This needs the live selectors for the search box and filter controls.
  URL-based navigation (recommended → preferred → all) remains the default.
- **Exact Gemini model string** — discovered at runtime via `models`, not hardcoded.
- **§16 — extra terminal states** (Requires Human Review, AI Failed, Cached) beyond
  the current Selected/Rejected/Duplicate/Applied flow.

The critical path is unchanged: verify the live card (and detail) selectors with
Visual Debug Mode, then I wire the detail-open + cache-fill flow and the verified
selectors. Everything is built to consume them.
