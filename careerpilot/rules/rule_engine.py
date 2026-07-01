"""Rule Engine -- deterministic, AI-free filtering (P006).

Answers one question: "Is this job worth sending to the AI?" Rules execute
cheapest-first and return the first matching rejection reason, so AI only ever
sees jobs that survive every rule. Everything is driven by ``RuleConfig`` --
no hardcoded thresholds, titles, or keywords.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.config import RuleConfig
from ..core.enums import RejectionReason
from ..core.logging_setup import get_logger
from ..core.models import Job

logger = get_logger(__name__)

# Built-in off-domain terms used by the card-stage open/skip gate (prefilter).
# A card whose title contains one of these (and no accepted leadership term) is
# clearly not an IT-infrastructure / digital-workplace / GCC leadership role, so
# it is not worth opening. This is a denylist (FAIL-OPEN): anything NOT listed
# here is still opened and judged on the full JD. Tunable via rejected_titles.
OFF_DOMAIN_TERMS = {
    "cfo", "cmo", "chro", "chief financial", "finance", "financial", "accounts",
    "accounting", "audit", "taxation", "treasury", "sales", "presales",
    "business development", "marketing", "hospitality", "hotel", "chef",
    "culinary", "kitchen", "housekeeping", "nurse", "nursing", "doctor",
    "physician", "pharma", "medical", "clinical", "construction", "civil",
    "plant", "production", "mechanical", "legal", "lawyer", "advocate",
    "paralegal", "recruiter", "talent acquisition", "teacher", "professor",
    "faculty", "driver", "warehouse", "retail", "cashier", "beautician",
    "fashion", "interior", "real estate", "insurance agent",
}


@dataclass
class RuleResult:
    accepted: bool
    reason: RejectionReason | None = None


class RuleEngine:
    """Applies deterministic rules in a fixed, cheapest-first order."""

    def __init__(self, config: RuleConfig):
        self.cfg = config

    def evaluate(self, job: Job) -> RuleResult:
        """Run all rules. The first failure wins; otherwise accept."""
        for rule in (
            self._portal_rule,
            self._salary_rule,
            self._experience_rule,
            self._employment_type_rule,
            self._shift_rule,
            self._location_rule,
            self._title_rule,
            self._blacklist_rule,
            self._keyword_rule,
        ):
            result = rule(job)
            if not result.accepted:
                logger.info("Rejected '%s' @ %s: %s",
                            job.job_title, job.company, result.reason.value)
                return result
        return RuleResult(accepted=True)

    def prefilter(self, job: Job) -> RuleResult:
        """Cheap card-stage gate: decide ONLY whether a job is worth OPENING,
        from the card title. This is deliberately FAIL-OPEN: a job is opened
        unless its title clearly belongs to an unrelated domain (CFO, sales,
        finance, plant, medical, hotel, legal, ...). It must NEVER skip a job
        just because the title doesn't match an accepted phrase -- requiring an
        accepted-title match here is what caused 'never opened', since live card
        titles rarely contain the exact configured phrases. The real fit decision
        (matched/rejected) happens later on the COMPLETE JD via evaluate().
        """
        title = (job.job_title or "").lower().strip()
        if not title:
            return RuleResult(accepted=True)            # can't judge -> open

        # Clearly relevant -> always open.
        if self._has_accepted_title(title):
            return RuleResult(accepted=True)

        # Blacklisted company -> skip opening.
        company = (job.company or "").strip().lower()
        if company and company in {c.strip().lower()
                                   for c in self.cfg.blacklist_companies}:
            logger.info("[prefilter] skip-open '%s' @ %s: blacklisted company",
                        job.job_title, job.company)
            return RuleResult(False, RejectionReason.BLACKLISTED_COMPANY)

        # Off-domain denylist (built-in defaults + configured rejected_titles).
        # Word-boundary match so 'finance' doesn't trip 'financial-systems lead'
        # ... actually we WANT to skip finance; boundaries avoid e.g. 'sales' in
        # 'wholesales'. An accepted term anywhere overrides (handled above).
        denylist = OFF_DOMAIN_TERMS | {t.lower() for t in self.cfg.rejected_titles}
        for term in denylist:
            if re.search(rf"\b{re.escape(term)}\b", title):
                logger.info("[prefilter] skip-open '%s' @ %s: off-domain term "
                            "'%s'", job.job_title, job.company, term)
                return RuleResult(False, RejectionReason.INVALID_JOB_TITLE)

        # Not clearly relevant, but not clearly off-domain -> OPEN and let the
        # full-JD Rule/AI decide (fail-open).
        return RuleResult(accepted=True)

    # ---- individual rules ------------------------------------------------

    def _portal_rule(self, job: Job) -> RuleResult:
        from ..core.enums import Portal
        if job.portal not in {p.value for p in Portal}:
            return RuleResult(False, RejectionReason.PORTAL_NOT_ALLOWED)
        return RuleResult(True)

    def _salary_rule(self, job: Job) -> RuleResult:
        # Missing salary is allowed through (common for leadership roles).
        amount = _parse_salary_to_inr(job.salary)
        if amount is not None and self.cfg.minimum_salary > 0 \
                and amount < self.cfg.minimum_salary:
            return RuleResult(False, RejectionReason.SALARY_BELOW_THRESHOLD)
        return RuleResult(True)

    def _experience_rule(self, job: Job) -> RuleResult:
        years = _parse_experience_min(job.experience)
        if years is not None and years < self.cfg.minimum_experience:
            return RuleResult(False, RejectionReason.EXPERIENCE_MISMATCH)
        return RuleResult(True)

    def _employment_type_rule(self, job: Job) -> RuleResult:
        if not job.employment_type:
            return RuleResult(True)
        accepted = {t.lower() for t in self.cfg.accepted_employment_types}
        if job.employment_type.lower() not in accepted:
            return RuleResult(False, RejectionReason.WRONG_EMPLOYMENT_TYPE)
        return RuleResult(True)

    def _shift_rule(self, job: Job) -> RuleResult:
        if not job.shift:
            return RuleResult(True)
        rejected = {s.lower() for s in self.cfg.rejected_shifts}
        if job.shift.lower() in rejected:
            return RuleResult(False, RejectionReason.NIGHT_SHIFT)
        return RuleResult(True)

    def _location_rule(self, job: Job) -> RuleResult:
        if not job.location or not self.cfg.preferred_locations:
            return RuleResult(True)  # unknown/unconfigured -> let AI decide
        loc = job.location.lower()
        if any(pref.lower() in loc for pref in self.cfg.preferred_locations):
            return RuleResult(True)
        if "remote" in loc:
            return RuleResult(True)
        return RuleResult(False, RejectionReason.LOCATION_MISMATCH)

    def _title_rule(self, job: Job) -> RuleResult:
        title = job.job_title.lower()
        if not title:
            return RuleResult(True)
        # Explicit rejects take priority (use word boundaries to avoid
        # 'engineering director' tripping the 'engineer' reject).
        for bad in self.cfg.rejected_titles:
            if re.search(rf"\b{re.escape(bad.lower())}\b", title):
                # ...unless an accepted leadership term is also present.
                if not self._has_accepted_title(title):
                    return RuleResult(False, RejectionReason.INVALID_JOB_TITLE)
        if self.cfg.accepted_titles and not self._has_accepted_title(title):
            return RuleResult(False, RejectionReason.INVALID_JOB_TITLE)
        return RuleResult(True)

    def _has_accepted_title(self, title_lower: str) -> bool:
        return any(good.lower() in title_lower for good in self.cfg.accepted_titles)

    def _blacklist_rule(self, job: Job) -> RuleResult:
        company = job.company.strip().lower()
        if company and company in {c.strip().lower() for c in self.cfg.blacklist_companies}:
            return RuleResult(False, RejectionReason.BLACKLISTED_COMPANY)
        return RuleResult(True)

    def _keyword_rule(self, job: Job) -> RuleResult:
        if not self.cfg.required_keywords:
            return RuleResult(True)
        haystack = f"{job.job_title} {job.job_description}".lower()
        if any(kw.lower() in haystack for kw in self.cfg.required_keywords):
            return RuleResult(True)
        return RuleResult(False, RejectionReason.DOMAIN_MISMATCH)


# ---- parsing helpers (deterministic, best-effort) ------------------------

def _parse_salary_to_inr(salary: str) -> int | None:
    """Best-effort parse of salary strings like '35 LPA', '₹40,00,000'.

    Returns annual INR, or None if it can't be determined (never rejects on
    inability to parse).
    """
    if not salary:
        return None
    s = salary.lower().replace(",", "").replace("₹", "").replace("inr", "")
    lpa = re.search(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lac)", s)
    if lpa:
        return int(float(lpa.group(1)) * 100_000)
    crore = re.search(r"(\d+(?:\.\d+)?)\s*(?:cr|crore)", s)
    if crore:
        return int(float(crore.group(1)) * 10_000_000)
    plain = re.search(r"(\d{6,})", s)  # a raw rupee figure
    if plain:
        return int(plain.group(1))
    return None


def _parse_experience_min(experience: str) -> int | None:
    """Extract the minimum years from strings like '15-20 years', '18+ yrs'."""
    if not experience:
        return None
    m = re.search(r"(\d+)", experience)
    return int(m.group(1)) if m else None
