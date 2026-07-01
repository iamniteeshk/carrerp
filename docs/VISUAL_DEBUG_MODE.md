# Visual Debug Mode & Browser Engine Review (v2.3.0)

## Visual Debug Mode

A permanent, config-driven part of the Browser Engine. Off by default; when off,
behaviour is identical to before. Turn it on in `config.yaml`:

```yaml
debug:
  visual_mode: true
  pause_after_navigation_seconds: 2
  pause_before_scroll_seconds: 2
  pause_after_scroll_seconds: 1
  evidence_dir: debug
  log_first_n_jobs: 5
```

When enabled, the Browser Engine becomes fully observable:

- **Element overlays** — coloured outlines on detected elements (job cards red,
  buttons blue, search box green, pagination orange, Easy Apply purple, current
  card yellow). Immediately shows whether a selector matched anything.
- **Live status panel** — a floating on-page panel (Portal, State, Search,
  Location, Visible cards, Collected, Pass, Current Scroll %) updated each pass.
- **Configurable pauses** — only in debug mode; gated entirely behind
  `visual_mode`, so they never affect normal runs.
- **Selector diagnostics** — per selector: matched / visible / hidden counts.
- **Scroll diagnostics** — per pass: scroll position, document/viewport height,
  scroll %, new cards, duplicates, running total.
- **First-N jobs** — logs the first 5 extracted jobs (title, company, location,
  salary, Easy Apply, URL) to prove extraction works.
- **Zero-results anomaly** — if results are confirmed present but 0 cards parse,
  it does NOT continue silently: it saves a screenshot, HTML, selector
  diagnostics and state.
- **Evidence bundle** per page under
  `debug/session/<portal>/page_NNN/` — `screenshot.png`, `page.html`,
  `parsed_jobs.json`, `browser_state.json`, `timeline.json` (Navigate → DOM
  Ready → Network Idle → Results Visible → Scroll passes → End Of Results →
  Extraction Complete).

This is exactly the instrument for completing the live-DOM selectors: turn it on,
watch which selectors match (or don't), set `RESULTS_SELECTOR`, and the overlays
+ diagnostics confirm extraction immediately.

## Search ordering: recommended → preferred → all

Login matters because the best matches come from the logged-in *recommended
jobs* feed. The search plan is now ordered: **recommended jobs first** (the
logged-in feed), then **preferred-location** searches, then **all-locations** as
a broad fallback. De-duplicated by URL. If login can't be confirmed,
`ensure_logged_in` raises and that portal is skipped (no refresh loop), so
recommended jobs are simply unavailable until you log in.

## Browser Engine flaw review (requested)

Honest status of each item; most are already mitigated by earlier work, a few
are noted as future hardening (not done, to avoid over-engineering now).

| Concern | Status |
|---------|--------|
| Race conditions | Mitigated — one scheduler worker thread + one Playwright instance; no concurrent page access. |
| Extraction before rendering | Fixed — `wait_for_ready` + `observe_state` gate extraction; proven with real Playwright. |
| Selector inconsistencies | Centralized as per-portal constants (config/override) + new selector diagnostics to catch mismatches. |
| Duplicated parsing | `collect_incrementally` de-dupes by job URL each pass. |
| Duplicate job collection | De-duped in the collect loop and again in the pipeline (FOUND stage). |
| Infinite-scroll bugs | Bounded — `scroll_passes` cap + `max_no_new` end-of-results detection; cannot loop forever. |
| Memory leaks | Overlays live in page DOM and die on navigation; evidence goes to disk, not memory. |
| Browser resource leaks | `close_all()` reaps all contexts + Playwright; verified zero orphan processes. |
| Unnecessary page reloads | `navigate()` reuses the page when already on the target URL. |
| Unnecessary navigation | Search plan de-dupes URLs; navigate guard prevents same-URL reloads. |
| Missed retries | Self-healing via `ensure_healthy` (restarts a dead context). **Future:** a bounded retry on a transient `goto` failure is not yet added (deliberately, to avoid masking real errors). |
| Timeout handling | `networkidle` is bounded and logs-then-proceeds; no silent infinite waits. |
| State transitions | Page-level `BrowserState` logged at every step; workflow-level `WorkflowState` validated. |
| Browser recovery | Per-portal restart + full teardown. **Future:** mid-scan crash resume (Phase 3 pause/resume queue). |

Nothing here required a rewrite; these are reinforcements of the existing engine.
