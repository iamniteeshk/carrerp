"""Confidence gate.

This is what lets "automated" and "quality" coexist. A job is auto-submitted
only when it clears every check below. Anything that fails is routed to
approval (or manual review) instead of being submitted blind.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import ApplyConfig
from ..core.logging_setup import get_logger
from ..core.models import AIEvaluation, Job

logger = get_logger(__name__)


@dataclass
class GateDecision:
    proceed: bool          # may we attempt the application at all?
    needs_approval: bool   # require human one-tap approval first?
    reason: str = ""


class ConfidenceGate:
    def __init__(self, config: ApplyConfig, min_score: float,
                 applied_so_far_lifetime: int = 0):
        self.cfg = config
        self.min_score = min_score
        self._applied_lifetime = applied_so_far_lifetime

    def decide(self, job: Job, evaluation: AIEvaluation,
               applied_today: int) -> GateDecision:
        if applied_today >= self.cfg.max_applications_per_day:
            return GateDecision(False, False, "daily application cap reached")

        if evaluation.match_score < self.min_score:
            return GateDecision(False, False,
                                f"score {evaluation.match_score} < {self.min_score}")

        if not evaluation.apply:
            return GateDecision(False, False, "AI advised not to apply")

        if self.cfg.easy_apply_only and not job.is_easy_apply:
            return GateDecision(False, False, "not Easy Apply / native apply")

        # First-run confirmation window: the first N live applications require
        # a human tap before the system is trusted unattended.
        if self._applied_lifetime < self.cfg.first_run_confirmations:
            return GateDecision(True, True, "first-run confirmation window")

        # Production default: always stop before final Submit and wait for an
        # explicit human confirmation. Set require_final_confirmation: false
        # only after sufficient live validation.
        if getattr(self.cfg, "require_final_confirmation", True):
            return GateDecision(True, True, "final confirmation required before submit")

        if self.cfg.mode == "live":
            return GateDecision(True, False, "auto-submit")
        return GateDecision(True, True, "dry-run mode")
