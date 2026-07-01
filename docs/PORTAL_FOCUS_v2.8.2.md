# Portal Focus & Quantitative Checklist — v2.8.2

This is the **final framework/tooling release**. From v2.8.3 onward every release
must move one or more Portal Completion Checklist items toward Production Ready by
implementing and validating real LinkedIn/Naukri functionality — not by adding
tooling. The framework (Browser/State/Diagnostics/Rule/AI engines) is mature.

## What changed in v2.8.2

The Portal Completion Checklist (kept from the prior release) now reports
**quantitative metrics**, not just states:

**Run-level (from the latest session report):**
- Last run timestamp; number of session reports on file
- Jobs found / rejected / matched / applied
- Success rates: match %, apply %, reject %
- Failure evidence-bundle count

**Per-portal coverage percentages:**
- Completion score %
- Started % (>= In Progress), Tested+ %, Production-Ready %
- Live-evidence coverage % (how many items have real run evidence behind them)
- Job bundles captured, jobs with a full JD, JD capture rate %

**Per-item:** evidence count and last-verified timestamp (stamped each time a
real run promotes the item).

Baseline today (no live run yet): overall **48%**; LinkedIn started 93% /
tested+ 43% / production-ready 7%; Naukri started 92% / tested+ 46% /
production-ready 8%; live-evidence coverage **0%** for both — because no live run
has fed the checklist yet. That 0% is the honest headline: states above
In Progress are code/fixture-based, and the live-evidence column is what turns
them into Production Ready.

Run it: `python -m careerpilot.main checklist --evidence debug/`
(writes `debug/portal_checklist.md`; snapshot in `docs/PORTAL_CHECKLIST.md`).

## The rule from v2.8.3 onward

Each release picks checklist items and moves them rightward with REAL portal
work + validation, raising the live-evidence coverage % and the success rates.
No more framework. The checklist's numbers are the definition of done and the
measure of progress.

## How a future release will look (the loop)

1. Implement/verify a real capability (e.g. Naukri job-detail selectors).
2. Run with `debug.visual_mode: true`; CareerPilot writes evidence bundles +
   session report + selector/DOM-diff analysis.
3. `checklist --evidence debug/` promotes the affected items and the
   live-evidence coverage % and success rates rise.
4. The release notes cite the moved items and the new numbers.
