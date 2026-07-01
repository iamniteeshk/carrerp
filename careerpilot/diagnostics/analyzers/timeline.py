"""Browser Timeline analyzer (point #8).

Builds a human-readable, replayable timeline from the recorded events + state
transitions: each line is an HH:MM:SS-style offset and what happened. The raw
events remain in replay.json (so the session is replayable via diagnostics.replay).

Expected ctx key:
  events: recorder events (with "t" seconds-offset and "kind")
  start_label: optional run start label
"""

from __future__ import annotations

from .base import Analyzer, AnalysisResult

# Only the milestone-ish events make a useful timeline (skip the thousands of
# individual mouse_move points -- those stay in replay.json).
_MILESTONES = {"navigate", "transition", "wait", "click", "key"}


def _clock(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{(t % 3600) // 60:02d}:{t % 60:02d}"


class TimelineAnalyzer(Analyzer):
    name = "Browser Timeline"

    def analyze(self, ctx: dict) -> AnalysisResult:
        events = (ctx or {}).get("events", []) or []
        lines = []
        for e in events:
            if e.get("kind") not in _MILESTONES:
                continue
            kind = e["kind"]
            if kind == "navigate":
                detail = e.get("url", "")
            elif kind == "transition":
                detail = e.get("state", "")
            elif kind == "wait":
                detail = f"{e.get('reason', '')} ({e.get('ms', '')}ms)"
            else:
                detail = kind
            lines.append(f"{_clock(e.get('t', 0))}  {kind:<10} {detail}")

        if not lines:
            return AnalysisResult(self.name, summary="No timeline events.",
                                  severity="info")
        return AnalysisResult(
            self.name,
            summary=f"{len(lines)} timeline milestone(s); full event stream in "
                    "replay.json (replayable).",
            severity="info", findings=lines,
            data={"timeline": lines, "milestone_count": len(lines)})
