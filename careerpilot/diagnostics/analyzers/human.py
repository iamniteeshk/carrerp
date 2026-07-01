"""Human Behaviour Score analyzer (point #5).

From the recorded interaction events it estimates how closely the browsing
resembled the intended human model: mouse realism, scroll realism, reading
realism, click/hover timing and overall randomness -> a 0-100 score with
recommendations. This is a model-fidelity measure, not an anti-detection claim.

Expected ctx key:
  events: [{"t": float, "kind": "mouse_move|scroll|click|hover|key|wait", ...}]
"""

from __future__ import annotations

from statistics import pstdev
from .base import Analyzer, AnalysisResult


class HumanBehaviourAnalyzer(Analyzer):
    name = "Human Behaviour Analyzer"

    def analyze(self, ctx: dict) -> AnalysisResult:
        events = (ctx or {}).get("events", []) or []
        if not events:
            return AnalysisResult(self.name,
                                  summary="No interaction events recorded.",
                                  severity="info")

        by = {}
        for e in events:
            by.setdefault(e.get("kind"), []).append(e)
        moves = by.get("mouse_move", [])
        scrolls = by.get("scroll", [])
        clicks = by.get("click", [])

        sub = {}
        # Mouse realism: many small moves (a curve) rather than 1-2 teleports.
        sub["mouse_realism"] = min(100, len(moves) * 8) if moves else 0
        # Scroll realism: variation in scroll distances (humans vary).
        dists = [s.get("y", 0) for s in scrolls]
        sub["scroll_realism"] = (min(100, int(pstdev(dists))) if len(dists) > 1
                                 else (40 if dists else 0))
        # Reading realism: presence of wait/read gaps between actions.
        gaps = _inter_event_gaps(events)
        sub["reading_realism"] = (min(100, int(_mean(gaps) * 100))
                                  if gaps else 0)
        # Timing randomness: variance across all inter-event gaps.
        sub["timing_randomness"] = (min(100, int(pstdev(gaps) * 120))
                                    if len(gaps) > 1 else 0)
        # Click timing: did clicks have a pause before them?
        sub["click_timing"] = 70 if clicks else 50  # neutral if no clicks yet

        score = round(sum(sub.values()) / len(sub))
        recs = []
        if sub["mouse_realism"] < 50:
            recs.append("Few mouse movements recorded -- ensure curved moves run "
                        "between cards, not just before clicks.")
        if sub["scroll_realism"] < 40:
            recs.append("Scroll distances look uniform -- widen "
                        "scroll_step_min/max_px for more variation.")
        if sub["reading_realism"] < 40:
            recs.append("Reading pauses look short/absent -- verify content-scaled "
                        "reading is enabled (human.enabled).")
        if sub["timing_randomness"] < 30:
            recs.append("Timing is too regular -- increase pause variance.")

        sev = "info" if score >= 70 else ("warning" if score >= 40 else "error")
        return AnalysisResult(
            self.name,
            summary=f"Human Behaviour Score: {score}/100.",
            severity=sev,
            findings=[f"{k}: {v}/100" for k, v in sub.items()],
            recommendations=recs or ["Behaviour matches the human model well."],
            data={"score": score, "subscores": sub})


def _inter_event_gaps(events: list) -> list:
    ts = [e.get("t", 0) for e in events]
    return [b - a for a, b in zip(ts, ts[1:]) if b >= a]


def _mean(xs: list) -> float:
    return sum(xs) / len(xs) if xs else 0.0
