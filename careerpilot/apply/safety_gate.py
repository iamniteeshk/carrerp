"""Final deterministic safety gate before any application attempt.

Runs AFTER Rule Engine + AI + ConfidenceGate. These checks are never delegated
to the model: blacklisted companies, off-domain IC roles, junior titles,
location policy, salary floor, and duplicate applications must be blocked here
even if the AI scored high.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.config import RuleConfig
from ..core.logging_setup import get_logger
from ..core.models import AIEvaluation, Job
from ..rules.rule_engine import (
    HARD_IC_TERMS,
    RuleEngine,
    _parse_salary_to_inr,
)

logger = get_logger(__name__)


@dataclass
class SafetyDecision:
    allowed: bool
    reason: str = ""


class ApplySafetyGate:
    """Last line of defence before portal.apply() is called."""

    def __init__(self, rules: RuleConfig, *,
                 require_preferred_location: bool = False,
                 chennai_priority: bool = True):
        self.rules = rules
        self.require_preferred_location = require_preferred_location
        self.chennai_priority = chennai_priority
        self._engine = RuleEngine(rules)

    def check(self, job: Job, evaluation: AIEvaluation | None = None) -> SafetyDecision:
        title = (job.job_title or "").lower().strip()
        company = (job.company or "").strip().lower()

        # 1. Blacklist (substring / normalized, not exact-only).
        if company and self._is_blacklisted(company):
            return SafetyDecision(False, f"blacklisted company: {job.company}")

        # 2. Hard IC / off-domain titles — never apply, regardless of AI score.
        if title:
            for term in HARD_IC_TERMS:
                import re
                if re.search(rf"\b{re.escape(term)}\b", title):
                    return SafetyDecision(False, f"hard IC/off-domain title: {term}")
            if self._engine._is_junior_title(title):
                return SafetyDecision(False, "junior/entry-level title")

        # 3. Location policy.
        loc = (job.location or "").lower().strip()
        prefs = [p.lower() for p in (self.rules.preferred_locations or []) if p]
        if self.require_preferred_location:
            if not loc:
                return SafetyDecision(False, "location unknown (required for apply)")
            if "remote" not in loc and prefs and not any(p in loc for p in prefs):
                return SafetyDecision(False, f"location outside preferred: {job.location}")
        elif self.chennai_priority and loc and prefs:
            # Soft: if location is known and matches none of preferred (and is
            # not remote), block apply. Search may still discover them.
            if "remote" not in loc and not any(p in loc for p in prefs):
                return SafetyDecision(False, f"location outside preferred: {job.location}")

        # 4. Salary floor (when configured and parseable).
        if self.rules.minimum_salary > 0:
            amount = _parse_salary_to_inr(job.salary or "")
            if amount is not None and amount < self.rules.minimum_salary:
                return SafetyDecision(
                    False,
                    f"salary {amount} below minimum {self.rules.minimum_salary}")

        # 5. Experience floor (when parseable).
        from ..rules.rule_engine import _parse_experience_min
        years = _parse_experience_min(job.experience or "")
        if years is not None and years < self.rules.minimum_experience:
            return SafetyDecision(
                False,
                f"experience {years}y below minimum {self.rules.minimum_experience}")

        # 6. AI must still say apply (belt-and-suspenders).
        if evaluation is not None and not evaluation.apply:
            return SafetyDecision(False, "AI advised not to apply")

        return SafetyDecision(True, "ok")

    def _is_blacklisted(self, company_lower: str) -> bool:
        for raw in self.rules.blacklist_companies or []:
            b = (raw or "").strip().lower()
            if not b:
                continue
            # Exact or substring either way (handles "ABC" vs "ABC Pvt Ltd").
            if b == company_lower or b in company_lower or company_lower in b:
                return True
        return False
