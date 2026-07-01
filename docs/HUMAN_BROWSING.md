# Human-like Browsing, Real Extraction & Pipeline Validation (v2.4.0)

## The "zero jobs" root cause (fixed)

The empty CSV / empty database was NOT a pipeline bug. The pipeline (collect →
store → dedupe → Rule → AI → apply → DB → CSV) is built and tested; it was
starved because `_parse_result_cards()` was a stub returning `[]`. Proven: with a
real parser and correct selectors, a Naukri-like fixture page yields 3 parsed
jobs that flow into the Rule Engine as 2 accepted / 1 rejected.

## Real, config-driven extraction

`_parse_result_cards` is now a real generic parser in the Browser Engine: it
iterates the configured results selector and extracts title/company/location/
salary/experience/url from each card. Selectors are **config-driven** in
`config.yaml -> portals.<portal>` (results_selector + per-field selectors).
Shipped defaults are best-known but **UNVERIFIED** — turn on Visual Debug Mode,
run a search, and the selector diagnostics + overlays show immediately whether
they match the live DOM. Fixing a selector is a config edit, no code change.

## Pipeline validation mode

```
python -m careerpilot.main validate
```

Runs one real scan and reports every stage (Browser/Collector, Rule Engine, AI
Engine, Database, Reports) with counts, and STOPS with a clear, actionable
message at the first stage that unexpectedly produced zero — instead of silently
leaving you with an empty CSV.

## Human-like browsing (config-gated)

`config.yaml -> human:` (off by default; when off, behaviour is unchanged):

- **Gradual scrolling** — small/medium steps with variable pauses and the
  occasional small upward correction, instead of one jump to the footer.
- **Content-based reading pauses** — reading time is estimated from the visible
  text (words / WPM, bounded), so long descriptions take longer; never a fixed
  arbitrary sleep.
- **Eased mouse movement** — moves in steps with slight overshoot and a pause
  before clicking, rather than teleporting.

It is deterministic: all randomness comes from one seeded RNG, so a `seed`
reproduces identical behaviour (used in tests). Wired into the incremental
collect loop: read visible jobs → gradual scroll → read newly loaded jobs →
repeat. Each visible section is processed before moving on.

## Honest status

- Extraction machinery: real and tested (parser proven against a fixture; full
  chain proven into the Rule Engine).
- Live selectors: the shipped defaults are educated guesses. They must be
  verified against the live DOM with Visual Debug Mode — that is the one step
  that genuinely needs your logged-in session, and `validate` + `visual_mode`
  are the tools to do it quickly.
- Nothing removed; State Engine, Rule/AI Engines, Human Interaction Engine and
  Visual Debug Mode all intact.
