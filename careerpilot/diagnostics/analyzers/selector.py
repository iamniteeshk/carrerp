"""Selector learning analyzer (point #2).

When an expected selector matched nothing, this looks at what IS in the DOM and
recommends the closest candidate -- expected vs closest, match count, confidence,
possible replacement. It only RECOMMENDS; it never modifies selectors.

Expected ctx keys:
  expected_selector: "div.job-card"
  candidates: [{"selector": "div.srp-jobtuple-wrapper", "count": 22,
                "sample_text": "Director ..."}, ...]
                (a list of class/structure candidates found in the live DOM,
                 produced by the toolkit's DOM survey)
"""

from __future__ import annotations

import re

from .base import Analyzer, AnalysisResult


def _tokens(selector: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (selector or "").lower()))


def _similarity(expected: str, candidate: str) -> float:
    """Token overlap (Jaccard) between two selectors, 0..1."""
    a, b = _tokens(expected), _tokens(candidate)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class SelectorAnalyzer(Analyzer):
    name = "Selector Analyzer"

    def analyze(self, ctx: dict) -> AnalysisResult:
        expected = (ctx or {}).get("expected_selector")
        candidates = (ctx or {}).get("candidates", []) or []
        if not expected:
            return AnalysisResult(self.name, summary="No expected selector given.",
                                  severity="info")
        if not candidates:
            return AnalysisResult(
                self.name,
                summary=f"'{expected}' matched nothing and no DOM candidates were "
                        "captured.", severity="warning",
                recommendations=["Capture a DOM survey (job-card-like containers) "
                                 "so a replacement can be suggested."])

        scored = []
        for c in candidates:
            sel = c.get("selector", "")
            count = c.get("count", 0)
            sim = _similarity(expected, sel)
            # Confidence blends name similarity with 'has a plausible card count'.
            plausible = 1.0 if 3 <= count <= 60 else (0.5 if count else 0.0)
            confidence = round(100 * (0.6 * sim + 0.4 * plausible))
            scored.append({"selector": sel, "count": count,
                           "similarity": round(sim, 2), "confidence": confidence,
                           "sample_text": c.get("sample_text", "")})
        scored.sort(key=lambda x: x["confidence"], reverse=True)
        best = scored[0]
        return AnalysisResult(
            self.name,
            summary=(f"'{expected}' matched 0 elements. Closest candidate: "
                     f"'{best['selector']}' ({best['count']} elements, "
                     f"confidence {best['confidence']}%)."),
            severity="warning",
            findings=[f"{c['selector']} -- {c['count']} els, "
                      f"sim={c['similarity']}, confidence={c['confidence']}%"
                      for c in scored[:5]],
            recommendations=[
                f"CONSIDER replacing '{expected}' with '{best['selector']}' in "
                f"config.yaml -> portals (recommendation only; not auto-applied)."],
            data={"expected": expected, "closest": best, "ranked": scored[:5]})
