"""Diagnostics Toolkit -- a first-class component that makes the Browser Engine
fully observable: interaction recording, console/network capture, one-shot DOM
export, automatic failure-evidence bundles, selector inspection and a live
status sink. It only observes and records; it never drives application logic.
"""

from .recorder import InteractionRecorder
from .exporter import export_page
from .evidence import FailureEvidence
from .live_status import LiveStatus
from .metrics import RunMetrics
from .session_report import SessionReporter
from .toolkit import (DiagnosticsToolkit, build_snapshot, survey_card_candidates)

__all__ = ["InteractionRecorder", "export_page", "FailureEvidence",
           "LiveStatus", "RunMetrics", "SessionReporter", "DiagnosticsToolkit",
           "build_snapshot", "survey_card_candidates"]
