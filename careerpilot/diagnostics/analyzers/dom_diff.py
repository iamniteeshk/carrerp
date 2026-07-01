"""DOM difference engine (point #3).

Compares two DOM snapshots (e.g. a baseline saved yesterday vs the current page)
and reports what changed: tag counts, class names that appeared/disappeared, and
the change in match counts for the selectors we rely on. This catches "22 cards
yesterday, 0 today" and explains it as a layout/class change rather than an
empty search.

A snapshot is a small dict (cheap to persist):
  {"tag_counts": {"div": 120, ...}, "classes": {"job-card": 22, ...},
   "selector_counts": {"job_card": 22}}
The toolkit builds a snapshot from a page via build_snapshot(page, selectors).
"""

from __future__ import annotations

from .base import Analyzer, AnalysisResult


class DomDiffAnalyzer(Analyzer):
    name = "DOM Diff Analyzer"

    def analyze(self, ctx: dict) -> AnalysisResult:
        base = (ctx or {}).get("baseline_snapshot")
        cur = (ctx or {}).get("current_snapshot")
        if not base or not cur:
            return AnalysisResult(self.name,
                                  summary="No baseline/current snapshot to compare.",
                                  severity="info")

        findings = []
        recs = []
        severity = "info"

        # Selector match-count changes (the headline signal).
        bsel = base.get("selector_counts", {})
        csel = cur.get("selector_counts", {})
        for name in sorted(set(bsel) | set(csel)):
            before, after = bsel.get(name, 0), csel.get(name, 0)
            if before != after:
                findings.append(f"selector '{name}': {before} -> {after} matches")
                if before > 0 and after == 0:
                    severity = "error"
                    recs.append(f"'{name}' broke (was {before}, now 0) -- almost "
                                "certainly a DOM/class change, not an empty search.")

        # Class appearance/disappearance.
        bcls, ccls = base.get("classes", {}), cur.get("classes", {})
        disappeared = [c for c in bcls if c not in ccls]
        appeared = [c for c in ccls if c not in bcls]
        if disappeared:
            findings.append(f"classes gone: {', '.join(sorted(disappeared)[:10])}")
        if appeared:
            findings.append(f"new classes: {', '.join(sorted(appeared)[:10])}")
            recs.append("New class names may be the renamed cards -- feed them to "
                        "the Selector Analyzer for a replacement suggestion.")

        # Structural tag-count drift.
        btags, ctags = base.get("tag_counts", {}), cur.get("tag_counts", {})
        drift = {t: ctags.get(t, 0) - btags.get(t, 0) for t in set(btags) | set(ctags)}
        big = {t: d for t, d in drift.items() if abs(d) >= 20}
        if big:
            findings.append("large tag-count drift: " +
                            ", ".join(f"{t}{'+' if d>0 else ''}{d}"
                                      for t, d in sorted(big.items())))

        if not findings:
            return AnalysisResult(self.name,
                                  summary="No significant DOM changes detected.",
                                  severity="info")
        return AnalysisResult(
            self.name,
            summary=f"DOM changed in {len(findings)} way(s) vs baseline.",
            severity=severity, findings=findings, recommendations=recs,
            data={"disappeared_classes": disappeared, "appeared_classes": appeared})


def diff_snapshots(baseline: dict, current: dict) -> AnalysisResult:
    return DomDiffAnalyzer().analyze({"baseline_snapshot": baseline,
                                      "current_snapshot": current})
