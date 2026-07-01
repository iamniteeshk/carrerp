# Autonomous Diagnostics & Browser Intelligence — v2.8.1

The Diagnostics Toolkit now *understands* what it records, via a plugin layer of
analyzers. Every analyzer is a pure function over captured data, so all are
deterministic and unit-tested (129 tests total). The core toolkit never changes
to add a diagnostic -- you register an Analyzer (point #9).

## Delivered (mapped to your points)

1. **Self-diagnosing browser** -- `FailureAnalyzer` turns page signals into
   ranked likely causes (logged out, layout change, still loading, CAPTCHA,
   redirect to login, network timeout, DOM change, overlay) each with evidence
   and a confidence, plus recommendations.
2. **Selector learning** -- `SelectorAnalyzer` compares the expected selector
   against DOM candidates and recommends the closest (match count + token
   similarity + confidence). Recommends only; never modifies selectors.
3. **DOM Difference Engine** -- `DomDiffAnalyzer` compares a baseline snapshot to
   the current one (tag counts, class appear/disappear, selector match-count
   changes) and flags "22 -> 0 = DOM change, not an empty search".
   `build_snapshot(page, selectors)` captures snapshots cheaply.
4. **Navigation intelligence** -- folded into the FailureAnalyzer: timeouts are
   explained (login appeared / idle never reached / spinner / CAPTCHA / zero
   jobs / redirect / overlay / unknown).
5. **Human Behaviour Score** -- `HumanBehaviourAnalyzer` scores mouse/scroll/
   reading/timing realism from recorded events -> 0-100 + recommendations
   (model-fidelity measure, explicitly not an anti-detection claim).
6. **Browser Health Report** -- `PerformanceAnalyzer` over `RunMetrics`: pages,
   jobs opened/parsed, selectors failed, retries, timeouts, avg read/scroll/
   job/AI/rule times, CSV/DB updates, memory/CPU (psutil if present),
   bottlenecks + recommendations.
7. **Automatic Session Summary** -- `SessionReporter` runs every analyzer at the
   end of a scan and writes `session_report_*.md` (+ JSON): searches, locations,
   discovered/opened/rejected/selected/queued/applied, AI/portal failures,
   evidence bundles, performance, warnings, suggestions. Generated automatically
   when debug mode is on.
8. **Browser Timeline** -- `TimelineAnalyzer` builds a clock-stamped milestone
   timeline; the full event stream stays in `replay.json` (replayable).
9. **Plugin architecture** -- `Analyzer` base + `SessionReporter.register()`;
   `default_analyzers()` ships six. A custom analyzer plugs in with no core
   change (tested).
10. **Production readiness review** -- see `ARCHITECTURE_REVIEW_v2.8.1.md`:
    findings + recommendations only, no changes made (largest file to split,
    `_safe` duplication, provider pluggability, cache size policy, etc.).

## Architecture

`careerpilot/diagnostics/` gains `analyzers/` (plugins), `metrics.py`,
`session_report.py`, and snapshot/survey helpers in `toolkit.py`. Analyzers
import nothing from Browser/Rule/AI engines -- they consume captured data only,
preserving the separation. Nothing existing was rewritten.

## How this helps the live-selector gap

When you run against the real sites with `debug.visual_mode: true`, a failed
selector now produces: an evidence bundle (HTML/screenshot/etc.), a ranked
failure diagnosis, a closest-selector recommendation, and -- if you keep a prior
snapshot -- a DOM diff showing exactly which class names changed. That turns
"why did it return zero?" from a manual investigation into a generated answer.
