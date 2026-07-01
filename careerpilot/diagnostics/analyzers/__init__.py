"""Analyzer plugins for the Diagnostics Toolkit (point #9).

Adding a new diagnostic = write an Analyzer subclass and register it. The core
toolkit never changes. ``default_analyzers()`` returns the built-in set.
"""

from .base import Analyzer, AnalysisResult
from .failure import FailureAnalyzer
from .selector import SelectorAnalyzer
from .dom_diff import DomDiffAnalyzer, diff_snapshots
from .human import HumanBehaviourAnalyzer
from .performance import PerformanceAnalyzer
from .timeline import TimelineAnalyzer


def default_analyzers() -> list:
    return [FailureAnalyzer(), SelectorAnalyzer(), DomDiffAnalyzer(),
            HumanBehaviourAnalyzer(), PerformanceAnalyzer(), TimelineAnalyzer()]


__all__ = ["Analyzer", "AnalysisResult", "FailureAnalyzer", "SelectorAnalyzer",
           "DomDiffAnalyzer", "diff_snapshots", "HumanBehaviourAnalyzer",
           "PerformanceAnalyzer", "TimelineAnalyzer", "default_analyzers"]
