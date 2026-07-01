"""Analyzer plugin base.

An Analyzer turns recorded diagnostics (signals, selector reports, interaction
events, DOM snapshots, run metrics) into an explanation: what happened, why,
the supporting evidence, and what to improve. Analyzers are pure functions over
captured DATA (not a live browser), which keeps them deterministic and testable.

New diagnostics are added by writing an Analyzer and registering it -- the core
toolkit never changes (the plugin architecture, point #9).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class AnalysisResult:
    analyzer: str
    summary: str = ""
    severity: str = "info"            # info | warning | error
    findings: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"analyzer": self.analyzer, "summary": self.summary,
                "severity": self.severity, "findings": self.findings,
                "recommendations": self.recommendations, "data": self.data}

    def as_markdown(self) -> str:
        icon = {"info": "i", "warning": "!", "error": "x"}.get(self.severity, "-")
        lines = [f"### [{icon}] {self.analyzer}", "", self.summary or ""]
        if self.findings:
            lines += ["", "**Findings:**"] + [f"- {f}" for f in self.findings]
        if self.recommendations:
            lines += ["", "**Recommendations:**"] + \
                     [f"- {r}" for r in self.recommendations]
        return "\n".join(lines)


class Analyzer(abc.ABC):
    """Contract for a diagnostics plugin."""

    name: str = "analyzer"

    @abc.abstractmethod
    def analyze(self, ctx: dict) -> AnalysisResult:
        """Inspect the diagnostics ``ctx`` and return findings. Must not raise;
        return an info result if there's nothing relevant to analyze."""
        raise NotImplementedError
